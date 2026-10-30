"""HTTPS wrapper for the MusicBee Tagger MCP server.

Runs the MCP server with StreamableHTTP transport on localhost HTTP and wraps it
with TLS so Claude Desktop can connect via https://localhost:8443/mcp.
"""

import http.server
import ipaddress
import json
import os
import ssl
import subprocess
import sys
import time
from pathlib import Path

MCP_INTERNAL_HOST = "127.0.0.1"
MCP_INTERNAL_PORT = int(os.environ.get("MCP_INTERNAL_PORT", "8000"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8443"))

CERT_DIR = Path(os.environ.get("MCP_CERT_DIR", "/certs"))
CERT_FILE = CERT_DIR / os.environ.get("MCP_CERT_FILE", "cert.pem")
KEY_FILE = CERT_DIR / os.environ.get("MCP_KEY_FILE", "key.pem")

MCP_MODULE = "musicbee_tagger_mcp.server"


def _start_mcp_stdio() -> subprocess.Popen:
    env = dict(os.environ)
    env["MUSICBEE_TAGGER_DATA_DIR"] = env.get("MUSICBEE_TAGGER_DATA_DIR", "/data")
    proc = subprocess.Popen(
        [sys.executable, "-m", MCP_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    return proc


class _MCPStreamReader:
    def __init__(self, proc: subprocess.Popen):
        self._proc = proc

    def read_message(self) -> dict | None:
        line = self._proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            return self.read_message()
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"error": "invalid json from MCP server", "raw": line[:200]}


class _MCPStreamWriter:
    def __init__(self, proc: subprocess.Popen):
        self._proc = proc

    def write_message(self, message: dict) -> None:
        text = json.dumps(message, ensure_ascii=False) + "\n"
        self._proc.stdin.write(text)
        self._proc.stdin.flush()


class MCPHTTPHandler(http.server.BaseHTTPRequestHandler):
    mcp_proc: subprocess.Popen | None = None
    mcp_reader: _MCPStreamReader | None = None
    mcp_writer: _MCPStreamWriter | None = None

    def log_message(self, format, *args):
        return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "musicbee-tagger-mcp"})
            return
        if self.path == "/":
            self._send_json(200, {
                "name": "musicbee-tagger-mcp",
                "version": "0.4.5",
                "transport": "https",
                "endpoint": "/mcp",
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/mcp":
            self._send_json(404, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        try:
            message = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        try:
            assert MCPHTTPHandler.mcp_writer is not None
            assert MCPHTTPHandler.mcp_reader is not None
            MCPHTTPHandler.mcp_writer.write_message(message)
            response = MCPHTTPHandler.mcp_reader.read_message()
            if response is None:
                self._send_json(502, {"error": "MCP server closed connection"})
                return
            self._send_json(200, response)
        except Exception as exc:
            self._send_json(502, {"error": f"MCP relay error: {exc}"})


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
                x509.SubjectAlternativeName(
                    [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
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
        import subprocess as _sp
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        _sp.run(
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
    mcp_proc = _start_mcp_stdio()
    MCPHTTPHandler.mcp_proc = mcp_proc
    MCPHTTPHandler.mcp_writer = _MCPStreamWriter(mcp_proc)
    MCPHTTPHandler.mcp_reader = _MCPStreamReader(mcp_proc)

    time.sleep(0.5)

    _ensure_certs()

    server = http.server.ThreadingHTTPServer((MCP_HOST, MCP_PORT), MCPHTTPHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print(
        f"musicbee-tagger-mcp HTTPS listening on {MCP_HOST}:{MCP_PORT} "
        f"(MCP stdio backend on {MCP_INTERNAL_HOST}:{MCP_INTERNAL_PORT})",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if mcp_proc.poll() is None:
            mcp_proc.terminate()
            try:
                mcp_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mcp_proc.kill()


if __name__ == "__main__":
    main()