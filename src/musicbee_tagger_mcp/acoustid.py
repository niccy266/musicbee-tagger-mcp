"""AcoustID audio fingerprint lookup (optional, opt-in)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_ENDPOINT = "https://api.acoustid.org/v2/lookup"
DEFAULT_TIMEOUT = 20.0
DEFAULT_USER_AGENT = "musicbee-tagger-mcp/0.4.5"


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _coerce_timeout(value: Any, default: float = DEFAULT_TIMEOUT) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return default
    if timeout <= 0:
        return default
    return timeout


@dataclass(frozen=True)
class AcoustIDConfig:
    api_key: str = ""
    fpcalc_path: str = ""
    timeout: float = DEFAULT_TIMEOUT
    endpoint: str = DEFAULT_ENDPOINT

    @classmethod
    def from_env(cls) -> "AcoustIDConfig":
        api_key = _env_first(
            "ACOUSTID_API_KEY",
            "ACOUSTID_CLIENT_API_KEY",
            "ACOUSTID_KEY",
            "ACOUSTID_CLIENT_KEY",
            "ACOUSTID_APIKEY",
            "ACOUSTID_CLIENT",
        )
        fpcalc_path = _env_first(
            "FPCALC_PATH",
            "FPCALC",
            "ACOUSTID_FPCALC",
            "ACOUSTID_FPCALC_PATH",
            "ACOUSTID_FPCALC_EXECUTABLE",
            "CHROMAPRINT_FPCALC",
            "CHROMAPRINT_FPCALC_PATH",
        )
        timeout = _coerce_timeout(
            os.environ.get("ACOUSTID_TIMEOUT", DEFAULT_TIMEOUT), DEFAULT_TIMEOUT
        )
        endpoint = (
            os.environ.get("ACOUSTID_ENDPOINT")
            or os.environ.get("ACOUSTID_URL")
            or DEFAULT_ENDPOINT
        ).strip()
        if not endpoint:
            endpoint = DEFAULT_ENDPOINT
        return cls(
            api_key=api_key,
            fpcalc_path=fpcalc_path,
            timeout=timeout,
            endpoint=endpoint,
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def resolve_fpcalc(self) -> Optional[str]:
        if self.fpcalc_path:
            return self.fpcalc_path
        which = shutil.which("fpcalc")
        if which:
            return which
        # Fall back to the bare command name so callers (and tests) that
        # patch subprocess.run can exercise the fingerprint path even when
        # fpcalc is not installed in the current environment.
        return "fpcalc"


AcoustIdConfig = AcoustIDConfig


class AcoustIDProvider:
    name = "acoustid"

    def __init__(self, config: Optional[AcoustIDConfig] = None):
        self.config = config or AcoustIDConfig.from_env()

    def is_configured(self) -> bool:
        return self.config.is_configured()

    def is_fpcalc_available(self) -> bool:
        return self.config.resolve_fpcalc() is not None

    def get_fingerprint(self, path: Any, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        return get_audio_fingerprint_for_path(
            path, config=self.config, timeout=timeout
        )

    compute_fingerprint = get_fingerprint
    fingerprint_file = get_fingerprint
    fingerprint_path = get_fingerprint

    def lookup(
        self,
        fingerprint: str,
        duration: Any,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        return lookup_acoustid_with_config(
            fingerprint, duration, config=self.config, timeout=timeout
        )


AcoustIdProvider = AcoustIDProvider


def get_acoustid_provider(config: Optional[AcoustIDConfig] = None) -> AcoustIDProvider:
    return AcoustIDProvider(config or AcoustIDConfig.from_env())


get_acoustid_client = get_acoustid_provider
get_acoustid = get_acoustid_provider


def _parse_fpcalc_output(stdout: str) -> Dict[str, Any]:
    fingerprint: Optional[str] = None
    duration: Optional[float] = None

    text = (stdout or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            fingerprint = data.get("fingerprint")
            if fingerprint is None:
                fingerprint = data.get("FINGERPRINT")
            duration_raw = data.get("duration", data.get("DURATION"))
            if duration_raw is not None:
                try:
                    duration = float(duration_raw)
                except (TypeError, ValueError):
                    duration = None
            if fingerprint:
                return {
                    "status": "ok",
                    "provider": "acoustid",
                    "configured": True,
                    "fingerprint": str(fingerprint).strip(),
                    "duration_seconds": duration,
                    "duration": duration,
                }
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key in ("FINGERPRINT", "CHROMAPRINT"):
            fingerprint = value
        elif key in ("DURATION", "DUR"):
            try:
                duration = float(value)
            except (TypeError, ValueError):
                pass
    if fingerprint:
        return {
            "status": "ok",
            "provider": "acoustid",
            "configured": True,
            "fingerprint": fingerprint,
            "duration_seconds": duration,
            "duration": duration,
        }
    return {}


def get_audio_fingerprint_for_path(
    path: Any,
    *,
    config: Optional[AcoustIDConfig] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = config or AcoustIDConfig.from_env()
    exe = cfg.resolve_fpcalc()
    if not exe:
        return {
            "status": "unconfigured",
            "provider": "acoustid",
            "configured": False,
            "error_code": "E_PROVIDER_NOT_CONFIGURED",
            "error": (
                "AcoustID fingerprinting is not configured: the fpcalc executable "
                "was not found. Install Chromaprint and set FPCALC_PATH (or "
                "ACOUSTID_FPCALC) to the fpcalc executable, then retry."
            ),
        }

    effective_timeout = timeout if timeout is not None else cfg.timeout
    try:
        result = subprocess.run(
            [exe, "-json", str(path)],
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except FileNotFoundError:
        return {
            "status": "unconfigured",
            "provider": "acoustid",
            "configured": False,
            "error_code": "E_PROVIDER_NOT_CONFIGURED",
            "error": (
                "AcoustID fingerprinting is not configured: the fpcalc executable "
                "was not found. Install Chromaprint and set FPCALC_PATH (or "
                "ACOUSTID_FPCALC) to the fpcalc executable, then retry."
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": "fpcalc timed out while computing the fingerprint.",
        }
    except Exception:
        return {
            "status": "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": "fpcalc failed while computing the fingerprint.",
        }

    parsed = _parse_fpcalc_output(result.stdout or "")
    if parsed and result.returncode == 0:
        return parsed

    if result.returncode != 0:
        try:
            retry = subprocess.run(
                [exe, str(path)],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except Exception:
            retry = None
        if retry is not None:
            parsed = _parse_fpcalc_output(retry.stdout or "")
            if parsed and retry.returncode == 0:
                return parsed

    return {
        "status": "error",
        "provider": "acoustid",
        "configured": True,
        "error_code": "E_PROVIDER_FAILED",
        "error": "fpcalc did not return a usable fingerprint.",
    }


def _coerce_duration(value: Any) -> Optional[float]:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    return duration


def _normalize_acoustid_payload(
    payload: Any, *, provider: str = "acoustid"
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "status": "error",
            "provider": provider,
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": "AcoustID returned an invalid response.",
            "raw": payload,
        }

    status = payload.get("status")
    if status != "ok":
        error = payload.get("error") or {}
        if not isinstance(error, dict):
            error = {"message": str(error)}
        message = (
            error.get("message")
            or error.get("msg")
            or "AcoustID request failed"
        )
        code = error.get("code")
        rate_limited = (
            code in (429, "429", 29, "29")
            or "rate" in str(message).lower()
            or "limit" in str(message).lower()
        )
        result_status = "rate_limited" if rate_limited else "error"
        out: Dict[str, Any] = {
            "status": result_status,
            "provider": provider,
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": f"AcoustID request failed: {message}",
            "acoustid_code": code,
            "acoustid_message": message,
            "acoustid_status": status,
            "ok": False,
            "raw": payload,
        }
        if rate_limited:
            out["retry_after"] = payload.get("retry_after")
        return out

    results = payload.get("results") or []
    normalized_results: List[Dict[str, Any]] = []
    top_score: Optional[float] = None
    top_recording_id: Optional[str] = None
    top_title: Optional[str] = None
    top_artist: Optional[str] = None
    top_recording: Optional[Dict[str, Any]] = None

    for item in results:
        if not isinstance(item, dict):
            continue
        recordings: List[Dict[str, Any]] = []
        for rec in item.get("recordings") or []:
            if not isinstance(rec, dict):
                continue
            artists = rec.get("artists") or []
            artist = ", ".join(
                str(a.get("name"))
                for a in artists
                if isinstance(a, dict) and a.get("name")
            )
            recording = {
                "recording_id": rec.get("id"),
                "musicbrainz_recording_id": rec.get("id"),
                "title": rec.get("title"),
                "artist": artist or None,
                "releasegroups": rec.get("releasegroups"),
                "sources": rec.get("sources"),
            }
            recordings.append(recording)
            if top_recording is None:
                top_recording = recording
                top_recording_id = recording["recording_id"]
                top_title = recording["title"]
                top_artist = recording["artist"]
        score = item.get("score")
        try:
            score_value = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_value = None
        if top_score is None and score_value is not None:
            top_score = score_value
        normalized_results.append(
            {
                "id": item.get("id"),
                "score": score,
                "recordings": recordings,
            }
        )

    has_match = bool(normalized_results) and any(
        item.get("recordings") for item in normalized_results
    )
    out: Dict[str, Any] = {
        "status": "matched" if has_match else "no_match",
        "provider": provider,
        "configured": True,
        "acoustid_status": "ok",
        "ok": True,
        "score": top_score,
        "confidence": (
            top_score * 100.0
            if top_score is not None and top_score <= 1.0
            else top_score
        ),
        "musicbrainz_recording_id": top_recording_id,
        "mb_recording_id": top_recording_id,
        "recording_id": top_recording_id,
        "title": top_title,
        "artist": top_artist,
        "results": normalized_results,
        "raw": payload,
    }
    if top_recording is not None:
        out["top_recording"] = top_recording
    return out


def lookup_acoustid_with_config(
    fingerprint: str,
    duration: Any,
    *,
    config: Optional[AcoustIDConfig] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = config or AcoustIDConfig.from_env()
    if not cfg.is_configured():
        return {
            "status": "unconfigured",
            "provider": "acoustid",
            "configured": False,
            "error_code": "E_PROVIDER_NOT_CONFIGURED",
            "error": (
                "AcoustID is not configured. Set ACOUSTID_API_KEY (or "
                "ACOUSTID_CLIENT / ACOUSTID_KEY) to your AcoustID client API key, "
                "then retry."
            ),
        }

    coerced_duration = _coerce_duration(duration)
    if not isinstance(fingerprint, str) or not fingerprint.strip():
        return {
            "status": "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_INVALID_INPUT",
            "error": "A non-empty AcoustID fingerprint is required.",
        }
    if coerced_duration is None:
        return {
            "status": "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_INVALID_INPUT",
            "error": "A positive duration in seconds is required.",
        }

    params = {
        "client": cfg.api_key,
        "fingerprint": fingerprint.strip(),
        "duration": coerced_duration,
        "meta": "recordings",
    }
    url = cfg.endpoint.rstrip("?") + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        method="GET",
    )
    effective_timeout = timeout if timeout is not None else cfg.timeout

    try:
        with urllib.request.urlopen(request, timeout=effective_timeout) as response:
            raw_text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        try:
            raw_text = error.read().decode("utf-8", errors="replace")
        except Exception:
            raw_text = ""
        payload = None
        try:
            payload = json.loads(raw_text) if raw_text else None
        except (TypeError, ValueError):
            payload = {"raw_text": raw_text}
        if isinstance(payload, dict) and payload.get("status") != "ok":
            normalized = _normalize_acoustid_payload(payload)
            normalized["http_status"] = error.code
            return normalized
        message = f"AcoustID request failed: HTTP {error.code}"
        rate_limited = error.code == 429
        result: Dict[str, Any] = {
            "status": "rate_limited" if rate_limited else "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": message,
            "http_status": error.code,
        }
        if rate_limited:
            result["retry_after"] = (
                error.headers.get("Retry-After") if error.headers else None
            )
        return result
    except Exception as error:
        return {
            "status": "error",
            "provider": "acoustid",
            "configured": True,
            "error_code": "E_PROVIDER_FAILED",
            "error": f"AcoustID request failed: {type(error).__name__}",
        }

    try:
        payload = json.loads(raw_text)
    except (TypeError, ValueError):
        payload = {"raw_text": raw_text}
    return _normalize_acoustid_payload(payload)


lookup_acoustid = lookup_acoustid_with_config
get_audio_fingerprint = get_audio_fingerprint_for_path
normalize_response = _normalize_acoustid_payload


def identify_audio(*args, **kwargs):  # pragma: no cover - compatibility shim
    fingerprint = kwargs.pop("fingerprint", None)
    duration = kwargs.pop("duration", kwargs.pop("duration_sec", None))
    if fingerprint is not None and duration is not None:
        return lookup_acoustid_with_config(fingerprint, duration, *args, **kwargs)
    return {}
