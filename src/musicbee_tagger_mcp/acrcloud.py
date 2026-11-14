"""ACRCloud identification provider and pluggable fingerprint interface."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable
from .error_codes import redact_paths

DEFAULT_REGION = "us-west-2"
DEFAULT_DATA_TYPE = "audio"
DEFAULT_SIGNATURE_VERSION = "1"
MAX_SAMPLE_BYTES = 1_000_000


def _load_secret_file() -> Dict[str, str]:
    """Load ACRCloud credentials from the secret file.

    ACRCloud requires three separate credentials: host, access_key, access_secret.
    The secret file (default: token_ACRcloud_key, overridable via ACRCLOUD_SECRET_FILE)
    may use key=value lines, e.g.:

        accessKey=f184f0ba...
        secretKey=46U9bCQs...
        host=identify-us-west-2.acrcloud.com

    A JSON object is also accepted as a fallback. Returns an empty dict if the
    file cannot be read or parsed.
    """
    secret_file = os.environ.get("ACRCLOUD_SECRET_FILE", "token_ACRcloud_key")
    candidate_paths = [secret_file]
    # Also check relative to this module's package root.
    try:
        candidate_paths.append(
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), secret_file)
        )
    except Exception:
        pass
    for path in candidate_paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except (FileNotFoundError, OSError, IOError):
            continue
        creds: Dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                creds[key.strip()] = value.strip()
        if creds:
            return creds
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {}
    return {}


@dataclass(frozen=True)
class ACRCloudConfig:
    access_key: str = ""
    access_secret: str = ""
    host: str = ""
    region: str = ""
    timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "ACRCloudConfig":
        access_key = (
            os.environ.get("ACRCLOUD_ACCESS_KEY")
            or os.environ.get("ACRCLOUD_KEY")
            or os.environ.get("ACR_ACCESS_KEY")
            or ""
        ).strip()
        access_secret = (
            os.environ.get("ACRCLOUD_ACCESS_SECRET")
            or os.environ.get("ACRCLOUD_SECRET")
            or os.environ.get("ACR_ACCESS_SECRET")
            or ""
        ).strip()
        host = (
            os.environ.get("ACRCLOUD_HOST")
            or os.environ.get("ACRCLOUD_ENDPOINT")
            or ""
        ).strip()
        region = (os.environ.get("ACRCLOUD_REGION") or "").strip()
        # Fallback: read credentials from secret file if any are missing.
        # ACRCloud requires three separate credentials: host, access_key, access_secret.
        if not access_key or not access_secret or not host:
            file_creds = _load_secret_file()
            if not access_key:
                access_key = (
                    file_creds.get("accessKey", "")
                    or file_creds.get("access_key", "")
                    or ""
                ).strip()
            if not access_secret:
                access_secret = (
                    file_creds.get("secretKey", "")
                    or file_creds.get("secret_key", "")
                    or ""
                ).strip()
            if not host:
                host = file_creds.get("host", "").strip()
        timeout_raw = os.environ.get("ACRCLOUD_TIMEOUT", "20")
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 20.0
        if timeout <= 0:
            timeout = 20.0
        return cls(
            access_key=access_key,
            access_secret=access_secret,
            host=host,
            region=region,
            timeout=timeout,
        )

    def is_configured(self) -> bool:
        return bool(self.access_key and self.access_secret)

    def resolved_host(self) -> str:
        if self.host:
            host = self.host
            if "://" in host:
                host = host.split("://", 1)[1]
            host = host.rstrip("/")
            if "/" in host:
                host = host.split("/", 1)[0]
            return host
        region = self.region or DEFAULT_REGION
        return f"identify-{region}.acrcloud.com"


@runtime_checkable
class FingerprintProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        ...

    def identify(
        self,
        audio_bytes: bytes,
        *,
        filename: Optional[str] = None,
        duration_sec: Optional[float] = None,
        data_type: str = DEFAULT_DATA_TYPE,
    ) -> Dict[str, Any]:
        ...

class ACRCloudProvider:
    name = "acrcloud"

    def __init__(self, config=None):
        self.config = config or ACRCloudConfig.from_env()

    def is_configured(self):
        return self.config.is_configured()

    def identify(self, audio_bytes, *, filename=None, duration_sec=None, data_type=DEFAULT_DATA_TYPE):
        if not self.is_configured():
            return {
                "status": "unconfigured",
                "provider": self.name,
                "configured": False,
                "error": (
                    "ACRCloud is not configured. Set ACRCLOUD_ACCESS_KEY and "
                    "ACRCLOUD_ACCESS_SECRET (and optionally ACRCLOUD_REGION or "
                    "ACRCLOUD_HOST), then retry."
                ),
            }
        if not audio_bytes:
            return {
                "status": "error",
                "provider": self.name,
                "configured": True,
                "error": "No audio bytes were provided for identification.",
            }

        sample = audio_bytes[:MAX_SAMPLE_BYTES]
        timestamp = str(int(time.time()))
        http_method = "POST"
        http_uri = "/v1/identify"
        string_to_sign = "\n".join(
            [
                http_method,
                http_uri,
                self.config.access_key,
                data_type,
                DEFAULT_SIGNATURE_VERSION,
                timestamp,
            ]
        )
        signature = base64.b64encode(
            hmac.new(
                self.config.access_secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")

        boundary = "----musicbee-tagger-acrcloud-boundary"
        body = _build_multipart_body(
            boundary=boundary,
            sample=sample,
            filename=filename or "sample.bin",
            fields={
                "access_key": self.config.access_key,
                "sample_bytes": str(len(sample)),
                "timestamp": timestamp,
                "signature": signature,
                "data_type": data_type,
                "signature_version": DEFAULT_SIGNATURE_VERSION,
            },
        )

        url = f"https://{self.config.resolved_host()}{http_uri}"
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "musicbee-tagger-mcp/0.4.6",
            },
            method=http_method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            try:
                raw_text = error.read().decode("utf-8", errors="replace")
            except Exception:
                raw_text = ""
            return {
                "status": "error",
                "provider": self.name,
                "configured": True,
                "http_status": error.code,
                "error": f"ACRCloud request failed: HTTP {error.code}",
                "raw": _safe_json(raw_text),
            }
        except Exception as error:
            return {
                "status": "error",
                "provider": self.name,
                "configured": True,
                "error": redact_paths(f"ACRCloud request failed: {type(error).__name__}: {error}"),
            }

        payload = _safe_json(raw_text)
        return _normalize_response(payload, provider=self.name, duration_sec=duration_sec)


def get_acrcloud_provider(config=None):
    return ACRCloudProvider(config or ACRCloudConfig.from_env())


ACRCloudClient = ACRCloudProvider
get_acrcloud_client = get_acrcloud_provider
FingerprintClient = ACRCloudProvider
def _build_multipart_body(*, boundary, sample, filename, fields):
    lines = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode("ascii"))
        lines.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
        )
        lines.append(str(value).encode("utf-8"))
        lines.append(b"\r\n")
    lines.append(f"--{boundary}\r\n".encode("ascii"))
    lines.append(
        (
            f'Content-Disposition: form-data; name="sample"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("ascii")
    )
    lines.append(sample)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(lines)


def _safe_json(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {"raw_text": text}


def _normalize_response(payload, *, provider, duration_sec):
    if not isinstance(payload, dict):
        return {
            "status": "error",
            "provider": provider,
            "configured": True,
            "error": "ACRCloud returned an invalid response.",
            "raw": payload,
        }

    status = payload.get("status") or {}
    code = status.get("code")
    message = status.get("msg") or status.get("message")
    if code not in (0, "0", None):
        if code in (1001, "1001"):
            return {
                "status": "no_match",
                "provider": provider,
                "configured": True,
                "acrcloud_code": code,
                "acrcloud_message": message or "No result",
                "raw": payload,
            }
        return {
            "status": "error",
            "provider": provider,
            "configured": True,
            "acrcloud_code": code,
            "acrcloud_message": message,
            "error": f"ACRCloud identification failed: {message or code}",
            "raw": payload,
        }

    metadata = payload.get("metadata") or {}
    music = metadata.get("music") or []
    if not music:
        custom = metadata.get("custom_files") or []
        if custom:
            item = custom[0]
            duration_ms = item.get("duration_ms")
            return {
                "status": "matched",
                "provider": provider,
                "configured": True,
                "match_type": "custom_file",
                "title": item.get("title"),
                "artist": None,
                "album": None,
                "duration_seconds": (
                    duration_ms / 1000.0 if duration_ms else None
                ),
                "score": None,
                "confidence": None,
                "acr_id": item.get("acrid"),
                "acrcloud_code": code,
                "acrcloud_message": message or "Success",
                "raw": payload,
            }
        return {
            "status": "no_match",
            "provider": provider,
            "configured": True,
            "acrcloud_code": code,
            "acrcloud_message": message or "No result",
            "raw": payload,
        }

    item = music[0]
    artists = item.get("artists") or []
    artist = ", ".join(
        str(artist.get("name")) for artist in artists if artist.get("name")
    )
    album_info = item.get("album") or {}
    album = album_info.get("name")
    duration_ms = item.get("duration_ms")
    score = item.get("score")
    confidence = None
    if score is not None:
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            confidence = None
    mb_recording_id = None
    composers = item.get("composers") or item.get("composer") or []
    if isinstance(composers, str):
        composer = composers
    elif isinstance(composers, dict):
        composer = composers.get("name")
    else:
        composer = ", ".join(
            str(entry.get("name") if isinstance(entry, dict) else entry)
            for entry in composers
            if (entry.get("name") if isinstance(entry, dict) else entry)
        )
    external = item.get("external_metadata") or {}
    mb_entries = external.get("musicbrainz") or []
    if mb_entries:
        first = mb_entries[0] or {}
        track = first.get("track") or {}
        mb_recording_id = track.get("id")

    return {
        "status": "matched",
        "provider": provider,
        "configured": True,
        "match_type": "music",
        "title": item.get("title"),
        "artist": artist or None,
        "album": album,
        "duration_seconds": (duration_ms / 1000.0) if duration_ms else None,
        "score": score,
        "confidence": confidence,
        "acr_id": item.get("acrid"),
        "musicbrainz_recording_id": mb_recording_id,
        "release_date": item.get("release_date"),
        "composer": composer or None,
        "genres": [
            genre.get("name")
            for genre in (item.get("genres") or [])
            if genre.get("name")
        ],
        "acrcloud_code": code,
        "acrcloud_message": message or "Success",
        "local_duration_diff_seconds": (
            round(abs(duration_sec - (duration_ms / 1000.0)), 2)
            if duration_sec is not None and duration_ms
            else None
        ),
        "raw": payload,
    }

ACRCloud = ACRCloudProvider

# Public aliases for compatibility with tests and alternative import names.
build_multipart_body = _build_multipart_body
normalize_response = _normalize_response
safe_json = _safe_json


def identify_audio(audio_bytes, *, filename=None, duration_sec=None, data_type=DEFAULT_DATA_TYPE, config=None):
    provider = get_acrcloud_provider(config) if config is not None else get_acrcloud_provider()
    return provider.identify(
        audio_bytes,
        filename=filename,
        duration_sec=duration_sec,
        data_type=data_type,
    )


def identify_file(path, *, duration_sec=None, config=None):
    import os

    with open(path, "rb") as handle:
        audio_bytes = handle.read()
    return identify_audio(
        audio_bytes,
        filename=os.path.basename(str(path)),
        duration_sec=duration_sec,
        config=config,
    )
