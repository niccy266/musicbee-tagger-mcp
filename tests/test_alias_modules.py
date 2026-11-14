"""Parametrized regression tests for all backward-compatibility alias modules."""

import importlib
import pytest


ALIAS_MODULE_EXPECTATIONS = [
    ("musicbee_tagger_mcp.acoustid_client", "AcoustIDClient"),
    ("musicbee_tagger_mcp.acoustid_provider", "AcoustIDProvider"),
    ("musicbee_tagger_mcp.acrcloud_client", "ACRCloudClient"),
    ("musicbee_tagger_mcp.acrcloud_provider", "ACRCloudClient"),
    ("musicbee_tagger_mcp.fingerprint", "ACRCloudClient"),
    ("musicbee_tagger_mcp.fingerprint_acoustid", "AcoustIDClient"),
    ("musicbee_tagger_mcp.genre", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.genre_cleaner", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.genre_clutter", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.genres", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.lastfm_canonical", "resolve_lastfm"),
    ("musicbee_tagger_mcp.lastfm_client", "resolve_lastfm"),
    ("musicbee_tagger_mcp.lastfm_resolver", "resolve_lastfm"),
    ("musicbee_tagger_mcp.musicbrainz_api", "musicbrainzngs"),
    ("musicbee_tagger_mcp.review_queue", "ReviewFlagStore"),
    ("musicbee_tagger_mcp.tools.genre", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.tools.genres", "clean_genre_clutter"),
    ("musicbee_tagger_mcp.tools.review_flags", "flag_for_review"),
]


@pytest.mark.parametrize("module_path,expected_symbol", ALIAS_MODULE_EXPECTATIONS)
def test_alias_module_exports_expected_symbol(module_path: str, expected_symbol: str) -> None:
    """Ensure compatibility alias modules import cleanly and export their target symbols."""
    mod = importlib.import_module(module_path)
    assert hasattr(mod, expected_symbol), f"{module_path} missing expected symbol {expected_symbol}"
    assert getattr(mod, expected_symbol) is not None
