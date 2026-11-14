"""Unit tests for optional AcoustID fingerprint tools."""

import json
from unittest.mock import MagicMock, patch

from musicbee_tagger_mcp.acoustid import (
    AcoustIDConfig,
    AcoustIDProvider,
    _parse_fpcalc_output,
    get_audio_fingerprint_for_path,
    lookup_acoustid_with_config,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def close(self):
        """HTTPError hands its body to a _TemporaryFileCloser on 3.14."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ACOUSTID_API_KEY", " key ")
    monkeypatch.setenv("FPCALC_PATH", " K:\\tools\\fpcalc.exe ")
    monkeypatch.setenv("ACOUSTID_TIMEOUT", "5")
    monkeypatch.setenv("ACOUSTID_ENDPOINT", "https://example.com/lookup")

    config = AcoustIDConfig.from_env()
    assert config.api_key == "key"
    assert config.fpcalc_path == "K:\\tools\\fpcalc.exe"
    assert config.timeout == 5.0
    assert config.endpoint == "https://example.com/lookup"
    assert config.is_configured() is True


def test_config_defaults_and_invalid_timeout(monkeypatch):
    for name in (
        "ACOUSTID_API_KEY",
        "ACOUSTID_CLIENT_API_KEY",
        "ACOUSTID_KEY",
        "ACOUSTID_CLIENT_KEY",
        "ACOUSTID_APIKEY",
        "ACOUSTID_CLIENT",
        "FPCALC_PATH",
        "ACOUSTID_FPCALC",
        "CHROMAPRINT_FPCALC",
        "ACOUSTID_TIMEOUT",
        "ACOUSTID_ENDPOINT",
        "ACOUSTID_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ACOUSTID_TIMEOUT", "not-a-number")

    config = AcoustIDConfig.from_env()
    assert config.api_key == ""
    assert config.fpcalc_path == ""
    assert config.timeout == 20.0
    assert config.endpoint == "https://api.acoustid.org/v2/lookup"
    assert config.is_configured() is False


def test_provider_unconfigured_lookup_does_not_call_network():
    provider = AcoustIDProvider(AcoustIDConfig())
    with patch("musicbee_tagger_mcp.acoustid.urllib.request.urlopen") as urlopen:
        result = provider.lookup("fp", 10)
    urlopen.assert_not_called()
    assert result["status"] == "unconfigured"
    assert result["configured"] is False


def test_fingerprint_success_mocked_subprocess():
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = json.dumps({"fingerprint": "abc123", "duration": 12.34})

    config = AcoustIDConfig(fpcalc_path="fpcalc")
    with patch("musicbee_tagger_mcp.acoustid.subprocess.run", return_value=fake) as run:
        result = get_audio_fingerprint_for_path("/tmp/track.mp3", config=config)

    assert result["status"] == "ok"
    assert result["fingerprint"] == "abc123"
    assert result["duration"] == 12.34
    assert run.call_args[0][0][:2] == ["fpcalc", "-json"]


def test_fingerprint_not_found_returns_unconfigured():
    config = AcoustIDConfig(fpcalc_path="definitely-missing-fpcalc")
    with patch(
        "musicbee_tagger_mcp.acoustid.subprocess.run",
        side_effect=FileNotFoundError("missing"),
    ):
        result = get_audio_fingerprint_for_path("/tmp/track.mp3", config=config)
    assert result["status"] == "unconfigured"
    assert result["configured"] is False
    assert "definitely-missing-fpcalc" not in result.get("error", "")


def test_lookup_success_mocked_api():
    config = AcoustIDConfig(api_key="key")
    payload = {
        "status": "ok",
        "results": [
            {
                "score": 0.9,
                "recordings": [
                    {
                        "id": "rec-1",
                        "title": "Test Title",
                        "artists": [{"name": "Test Artist"}],
                    }
                ],
            }
        ],
    }

    with patch(
        "musicbee_tagger_mcp.acoustid.urllib.request.urlopen",
        side_effect=lambda request, timeout=None: _FakeResponse(payload),
    ):
        result = lookup_acoustid_with_config("fp", 123.456, config=config)

    assert result["status"] == "matched"
    assert result["musicbrainz_recording_id"] == "rec-1"
    assert result["title"] == "Test Title"
    assert result["artist"] == "Test Artist"


def test_lookup_unconfigured():
    result = lookup_acoustid_with_config("fp", 10, config=AcoustIDConfig())
    assert result["status"] == "unconfigured"
    assert result["configured"] is False
    assert result["error_code"] == "E_PROVIDER_NOT_CONFIGURED"


def test_lookup_invalid_input():
    config = AcoustIDConfig(api_key="key")
    assert lookup_acoustid_with_config("", 10, config=config)["status"] == "error"
    assert lookup_acoustid_with_config("fp", 0, config=config)["status"] == "error"
    assert lookup_acoustid_with_config("fp", "bad", config=config)["status"] == "error"


def test_lookup_rate_limited():
    import urllib.error

    config = AcoustIDConfig(api_key="key")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "7"},
            _FakeResponse({"status": "error", "error": {"code": 429, "message": "rate limit"}}),
        )

    with patch("musicbee_tagger_mcp.acoustid.urllib.request.urlopen", side_effect=fake_urlopen):
        result = lookup_acoustid_with_config("fp", 10, config=config)

    assert result["status"] == "rate_limited"
    assert result.get("retry_after") == "7"


def test_parse_fpcalc_output_json():
    parsed = _parse_fpcalc_output(json.dumps({"fingerprint": "xyz", "duration": 42}))
    assert parsed["status"] == "ok"
    assert parsed["fingerprint"] == "xyz"
    assert parsed["duration"] == 42


def test_tools_unknown_token():
    from musicbee_tagger_mcp.tools import acoustid as tools

    with patch("musicbee_tagger_mcp.tools.acoustid.get_registry") as get_registry:
        get_registry.return_value.resolve.side_effect = KeyError("missing")
        result = tools.get_audio_fingerprint("bad-token")
    assert result["error_code"] == "E_UNKNOWN_TOKEN"


def test_tools_lookup_unconfigured_path_free(monkeypatch):
    for name in ("ACOUSTID_API_KEY", "ACOUSTID_CLIENT_API_KEY", "ACOUSTID_KEY", "ACOUSTID_CLIENT_KEY", "ACOUSTID_APIKEY", "ACOUSTID_CLIENT"):
        monkeypatch.delenv(name, raising=False)
    from musicbee_tagger_mcp.tools import acoustid as tools

    result = tools.lookup_acoustid("fp", 10)
    assert result["status"] == "unconfigured"
    assert "K:\\" not in str(result)
    assert result["configured"] is False
