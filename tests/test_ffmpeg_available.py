"""Smoke check for the ffmpeg binary used by audio-fixture tests."""

import shutil

import pytest


@pytest.mark.requires_audio_fixtures
def test_ffmpeg_available():
    """ffmpeg must be present; otherwise audio-fixture tests skip loudly."""
    assert shutil.which("ffmpeg") is not None, "ffmpeg is required for audio fixture tests"
