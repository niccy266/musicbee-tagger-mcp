"""HTTPS wrapper for the MusicBee Tagger MCP server.

Runs the MCP server over stdio as a child process and exposes it as a
Streamable-HTTP style endpoint (POST /mcp) wrapped in TLS, so clients such as
Claude Desktop (via mcp-remote) can connect to https://localhost:8443/mcp.

Relay rules (why this file differs from the first version):
  * The child's stderr is NOT merged into stdout. The startup banner and any
    log lines go to the container log, never into the JSON-RPC channel.
  * A reader thread parses stdout and matches replies to requests by id, so
    concurrent HTTP requests no longer steal each other's replies.
  * Each request gets a unique internal id (clients all start at 0/1), and the
    client's original id is restored on the way back.
  * Notifications (no "id") are forwarded without waiting for a reply and get
    HTTP 202 with an empty body. Waiting for a reply that never comes was what
    caused the request timeouts.
  * Failures are returned as proper JSON-RPC error objects.
  * Non-JSON lines on stdout are logged and skipped instead of being returned
    to the client.
"""

import hmac
import http.server
import ipaddress
import itertools
import json
import os
import ssl
import subprocess
import sys
import threading
from pathlib import Path

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8443"))

# Tool calls (fingerprinting, MusicBrainz lookups) can be slow; clients apply
# their own timeouts on top of this.
REQUEST_TIMEOUT = float(os.environ.get("MCP_REQUEST_TIMEOUT", "120"))

# Optional bearer token for POST /mcp. When set, clients must send
# "Authorization: Bearer <token>". When empty, no auth is required.
AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

CERT_DIR = Path(os.environ.get("MCP_CERT_DIR", "/certs"))
CERT_FILE = CERT_DIR / os.environ.get("MCP_CERT_FILE", "cert.pem")
KEY_FILE = CERT_DIR / os.environ.get("MCP_KEY_FILE", "key.pem")

MCP_MODULE = "musicbee_tagger_mcp.server"


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _rpc_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class _StdioBackend:
    """The MCP server child process plus request/response matching."""

    def __init__(self) -> None:
        env = dict(os.environ)
        env.setdefault("MUSICBEE_TAGGER_DATA_DIR", "/data")
        self._proc = subprocess.Popen(
            [sys.executable, "-m", MCP_MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # inherit: banner/logs go to the container log
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, list] = {}  # internal id -> [Event, response]
        self._ids = itertools.count(1)
        threading.Thread(target=self._read_loop, daemon=True).start()

    def alive(self) -> bool:
        return self._proc.poll() is None

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _log(f"[backend stdout, ignored] {line[:200]}")
                continue
            if (
                not isinstance(msg, dict)
                or "method" in msg
                or not isinstance(msg.get("id"), int)
            ):
                # Server-initiated requests/notifications cannot be relayed
                # over plain POST request/response.
                _log(f"[backend message, not relayed] {line[:200]}")
                continue
            with self._pending_lock:
                slot = self._pending.get(msg["id"])
            if slot is None:
                _log(f"[backend reply with unknown id {msg['id']}, dropped]")
                continue
            slot[1] = msg
            slot[0].set()

        # stdout closed: the MCP process is gone. Exit so Docker restarts the
        # container (restart policy: unless-stopped) instead of hanging clients.
        _log("MCP stdio backend exited; shutting down wrapper")
        os._exit(1)

    def _send(self, message: dict) -> None:
        text = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            assert self._proc.stdin is not None
            self._proc.stdin.write(text)
            self._proc.stdin.flush()

    def notify(self, message: dict) -> None:
        self._send(message)

    def request(self, message: dict, timeout: float) -> dict:
        original_id = message["id"]
        internal_id = next(self._ids)
        slot: list = [threading.Event(), None]
        with self._pending_lock:
            self._pending[internal_id] = slot
        try:
            self._send({**message, "id": internal_id})
            if not slot[0].wait(timeout):
                raise TimeoutError(f"no reply from MCP backend within {timeout:g}s")
            response = dict(slot[1])
            response["id"] = original_id
            return response
        finally:
            with self._pending_lock:
                self._pending.pop(internal_id, None)


_backend: _StdioBackend | None = None


class MCPHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, status: int, payload, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def do_GET(self):
        path = self._path()
        if path == "/health":
            self._send_json(200, {
                "status": "ok",
                "service": "musicbee-tagger-mcp",
                "backend": "up" if _backend and _backend.alive() else "down",
            })
            return
        if path == "/":
            self._send_json(200, {
                "name": "musicbee-tagger-mcp",
                "version": "0.4.5",
                "transport": "https",
                "endpoint": "/mcp",
            })
            return
        if path == "/mcp":
            # Streamable HTTP clients may probe with GET for an SSE stream.
            self._send_json(405, {"error": "use POST"}, {"Allow": "POST"})
            return
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if self._path() == "/mcp":
            self._send_json(405, {"error": "sessions are stateless"}, {"Allow": "POST"})
            return
        self._send_json(404, {"error": "not found"})

    def _relay(self, msg):
        """Relay one JSON-RPC message. Returns a reply dict, or None if no reply."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            req_id = msg.get("id") if isinstance(msg, dict) else None
            return _rpc_error(req_id, -32600, "Invalid Request")
        if "method" not in msg:
            # A client->server response. We never forward server requests, so
            # there is nothing for it to answer.
            return None
        if "id" not in msg:
            # Notification. Cancellations carry the client's original request id,
            # which has been rewritten internally, so they are not forwarded.
            if msg["method"] != "notifications/cancelled":
                try:
                    _backend.notify(msg)
                except (OSError, ValueError) as exc:
                    _log(f"notify failed: {exc}")
            return None
        try:
            return _backend.request(msg, REQUEST_TIMEOUT)
        except TimeoutError as exc:
            return _rpc_error(msg["id"], -32001, str(exc))
        except (OSError, ValueError) as exc:
            return _rpc_error(msg["id"], -32603, f"MCP backend error: {exc}")

    def _authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {AUTH_TOKEN}")

    def do_POST(self):
        if self._path() != "/mcp":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            # 403 rather than 401: a 401 makes some clients start an OAuth flow.
            self._send_json(403, {"error": "missing or invalid bearer token"})
            return
        if _backend is None:
            self._send_json(503, _rpc_error(None, -32603, "backend not ready"))
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, _rpc_error(None, -32700, "Parse error"))
            return

        if isinstance(payload, list):
            if not payload:
                self._send_json(400, _rpc_error(None, -32600, "Invalid Request"))
                return
            replies = [r for r in (self._relay(m) for m in payload) if r is not None]
            if replies:
                self._send_json(200, replies)
            else:
                self._send_empty(202)
            return

        reply = self._relay(payload)
        if reply is None:
            self._send_empty(202)
        else:
            self._send_json(200, reply)


def _ensure_certs() -> None:
    if CERT_FILE.exists() and KEY_FILE.exists():
        return
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Sandbox"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MusicBee Tagger MCP"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=365)
            )
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    # x509.IPAddress needs an ipaddress object, not a string
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        KEY_FILE.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        KEY_FILE.chmod(0o600)
    except ImportError:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(KEY_FILE), "-out", str(CERT_FILE),
                "-days", "365", "-nodes",
                "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=False,
            capture_output=True,
        )


def main() -> None:
    global _backend
    _ensure_certs()
    _backend = _StdioBackend()

    server = http.server.ThreadingHTTPServer((MCP_HOST, MCP_PORT), MCPHTTPHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print(
        f"musicbee-tagger-mcp HTTPS listening on {MCP_HOST}:{MCP_PORT} "
        f"(stdio backend: python -m {MCP_MODULE}; "
        f"auth: {'bearer token required' if AUTH_TOKEN else 'NONE'})",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        proc = _backend._proc
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
