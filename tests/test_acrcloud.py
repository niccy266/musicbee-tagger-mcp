"""Unit tests for ACRCloud configuration, requests, and normalization."""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from musicbee_tagger_mcp import acrcloud
from musicbee_tagger_mcp.acrcloud import (
    ACRCloudConfig,
    ACRCloudProvider,
    _build_multipart_body,
    _normalize_response,
    identify_audio,
    identify_file,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        return None


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("ACRCLOUD_ACCESS_KEY", " key ")
    monkeypatch.setenv("ACRCLOUD_ACCESS_SECRET", " secret ")
    monkeypatch.setenv("ACRCLOUD_HOST", "https://example.com/path")
    monkeypatch.setenv("ACRCLOUD_REGION", "eu-west-1")
    monkeypatch.setenv("ACRCLOUD_TIMEOUT", "5")

    config = ACRCloudConfig.from_env()
    assert config.access_key == "key"
    assert config.access_secret == "secret"
    assert config.host == "https://example.com/path"
    assert config.region == "eu-west-1"
    assert config.timeout == 5.0
    assert config.resolved_host() == "example.com"


def test_config_defaults_and_invalid_timeout(monkeypatch):
    for name in (
        "ACRCLOUD_ACCESS_KEY",
        "ACRCLOUD_ACCESS_SECRET",
        "ACRCLOUD_HOST",
        "ACRCLOUD_REGION",
        "ACRCLOUD_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ACRCLOUD_TIMEOUT", "not-a-number")

    config = ACRCloudConfig.from_env()
    assert config.access_key == ""
    assert config.access_secret == ""
    assert config.timeout == 20.0
    assert config.resolved_host() == "identify-us-west-2.acrcloud.com"
    assert config.is_configured() is False


def test_provider_unconfigured_does_not_call_network():
    provider = ACRCloudProvider(ACRCloudConfig())
    with patch("musicbee_tagger_mcp.acrcloud.urllib.request.urlopen") as urlopen:
        result = provider.identify(b"audio", filename="track.mp3", duration_sec=10.0)
    urlopen.assert_not_called()
    assert result["status"] == "unconfigured"
    assert result["configured"] is False


def test_provider_identify_success(monkeypatch):
    monkeypatch.setattr(acrcloud.time, "time", lambda: 1234567890.0)
    config = ACRCloudConfig(
        access_key="access-key",
        access_secret="access-secret",
        region="us-west-2",
    )
    provider = ACRCloudProvider(config)

    payload = {
        "status": {"code": 0, "msg": "Success"},
        "metadata": {
            "music": [
                {
                    "title": "Test Title",
                    "artists": [{"name": "Test Artist"}],
                    "album": {"name": "Test Album"},
                    "duration_ms": 123456,
                    "score": 95,
                    "acrid": "acr-1",
                    "release_date": "2024-01-01",
                    "genres": [{"name": "Rock"}, {"name": None}],
                    "external_metadata": {
                        "musicbrainz": [{"track": {"id": "mb-recording-id"}}]
                    },
                }
            ]
        },
    }
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(payload)

    with patch("musicbee_tagger_mcp.acrcloud.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.identify(b"audio-bytes", filename="track.mp3", duration_sec=123.456)

    assert result["status"] == "matched"
    assert result["match_type"] == "music"
    assert result["title"] == "Test Title"
    assert result["artist"] == "Test Artist"
    assert result["album"] == "Test Album"
    assert result["musicbrainz_recording_id"] == "mb-recording-id"
    assert result["confidence"] == 95.0
    assert result["acrcloud_code"] == 0

    request = captured["request"]
    assert request.full_url == "https://identify-us-west-2.acrcloud.com/v1/identify"
    assert request.get_method() == "POST"
    body = request.data
    assert b"audio-bytes" in body
    assert b'name="access_key"' in body
    assert b"access-key" in body
    assert b'name="sample_bytes"' in body

    string_to_sign = "\n".join(
        [
            "POST",
            "/v1/identify",
            "access-key",
            "audio",
            "1",
            "1234567890",
        ]
    )
    expected_signature = base64.b64encode(
        hmac.new(
            b"access-secret",
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    assert expected_signature.encode("ascii") in body


def test_provider_no_match_and_custom_file():
    no_match_payload = {"status": {"code": 1001, "msg": "No result"}, "metadata": {}}
    assert _normalize_response(no_match_payload, provider="acrcloud", duration_sec=1.0)[
        "status"
    ] == "no_match"

    custom_payload = {
        "status": {"code": 0, "msg": "Success"},
        "metadata": {
            "custom_files": [{"title": "Custom", "duration_ms": 5000, "acrid": "custom-1"}]
        },
    }
    result = _normalize_response(custom_payload, provider="acrcloud", duration_sec=5.0)
    assert result["status"] == "matched"
    assert result["match_type"] == "custom_file"
    assert result["title"] == "Custom"
    assert result["artist"] is None
    assert result["acr_id"] == "custom-1"


def test_provider_http_error():
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {},
            _FakeResponse({"error": "bad"}),
        )

    config = ACRCloudConfig(access_key="k", access_secret="s")
    provider = ACRCloudProvider(config)
    with patch("musicbee_tagger_mcp.acrcloud.urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.identify(b"audio", filename="track.mp3")
    assert result["status"] == "error"
    assert result["http_status"] == 400


def test_multipart_body_contains_fields_and_sample():
    body = _build_multipart_body(
        boundary="BOUNDARY",
        sample=b"sample-bytes",
        filename="sample.mp3",
        fields={"access_key": "key", "sample_bytes": "11"},
    )
    text = body.decode("latin-1")
    assert "--BOUNDARY\r\n" in text
    assert 'name="access_key"' in text
    assert 'name="sample"; filename="sample.mp3"' in text
    assert "sample-bytes" in text
    assert body.endswith(b"--BOUNDARY--\r\n")


def test_identify_audio_and_file(tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"audio-file")
    config = ACRCloudConfig()  # unconfigured
    result = identify_audio(b"abc", config=config)
    assert result["status"] == "unconfigured"
    result = identify_file(audio, config=config)
    assert result["status"] == "unconfigured"
