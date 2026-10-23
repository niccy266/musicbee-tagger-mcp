"""Audio tag writer with diff preview, UTF-8 safety, and backup capabilities."""

import shutil
from pathlib import Path
from typing import Dict, Any, Optional
import mutagen
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TPE2, TDRC, TDOR, TRCK, UFID, TXXX
)
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
from .metadata_reader import read_audio_metadata

def preview_tag_changes(file_path: str, new_tags: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a field-by-field diff of proposed changes against current metadata
    without writing anything to disk.
    """
    current_meta = read_audio_metadata(file_path)
    current_tags = current_meta.get("tags", {})

    diff = {}
    has_changes = False

    all_keys = set(current_tags.keys()).union(set(new_tags.keys()))
    for key in sorted(all_keys):
        val_before = current_tags.get(key)
        val_after = new_tags.get(key, val_before)
        
        # Stringify for clean comparison
        str_before = str(val_before) if val_before is not None else ""
        str_after = str(val_after) if val_after is not None else ""

        changed = (str_before != str_after) and (key in new_tags)
        if changed:
            has_changes = True

        diff[key] = {
            "before": val_before,
            "after": val_after if key in new_tags else val_before,
            "changed": changed
        }

    return {
        "file_path": file_path,
        "has_changes": has_changes,
        "diff": diff
    }

def apply_tags_to_file(
    file_path: str,
    new_tags: Dict[str, Any],
    create_backup: bool = True
) -> Dict[str, Any]:
    """
    Safely write new tags to audio file using UTF-8 encoding.
    Creates an optional .bak file before modification.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Create backup if requested
    backup_path = None
    if create_backup:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)

    # Preview diff first
    preview = preview_tag_changes(file_path, new_tags)
    if not preview["has_changes"]:
        return {
            "file_path": file_path,
            "status": "skipped",
            "message": "No changes detected",
            "backup_created": False
        }

    audio = mutagen.File(file_path)
    if audio is None:
        raise ValueError(f"Unsupported format: {file_path}")

    # 1. MP3 (ID3v2.4 UTF-8)
    if hasattr(audio, "tags") and (isinstance(audio.tags, ID3) or path.suffix.lower() == ".mp3"):
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        # Encoding 3 = UTF-8 in ID3v2.4
        enc = 3

        if "title" in new_tags and new_tags["title"]:
            tags.setall("TIT2", [TIT2(encoding=enc, text=[str(new_tags["title"])])])
        if "artist" in new_tags and new_tags["artist"]:
            tags.setall("TPE1", [TPE1(encoding=enc, text=[str(new_tags["artist"])])])
        if "album" in new_tags and new_tags["album"]:
            tags.setall("TALB", [TALB(encoding=enc, text=[str(new_tags["album"])])])
        if "album_artist" in new_tags and new_tags["album_artist"]:
            tags.setall("TPE2", [TPE2(encoding=enc, text=[str(new_tags["album_artist"])])])
        if "year" in new_tags and new_tags["year"]:
            tags.setall("TDRC", [TDRC(encoding=enc, text=[str(new_tags["year"])])])
        if "original_year" in new_tags and new_tags["original_year"]:
            tags.setall("TDOR", [TDOR(encoding=enc, text=[str(new_tags["original_year"])])])
        if "track_number" in new_tags and new_tags["track_number"] is not None:
            tags.setall("TRCK", [TRCK(encoding=enc, text=[str(new_tags["track_number"])])])
        if "musicbrainz_track_id" in new_tags and new_tags["musicbrainz_track_id"]:
            tags.setall("UFID:http://musicbrainz.org", [
                UFID(owner="http://musicbrainz.org", data=str(new_tags["musicbrainz_track_id"]).encode("ascii"))
            ])
        if "musicbrainz_release_id" in new_tags and new_tags["musicbrainz_release_id"]:
            tags.setall("TXXX:MusicBrainz Album Id", [
                TXXX(encoding=enc, desc="MusicBrainz Album Id", text=[str(new_tags["musicbrainz_release_id"])])
            ])
        audio.save(v2_version=4)  # Force ID3v2.4 UTF-8

    # 2. FLAC / OGG (Vorbis Comments)
    elif isinstance(audio, (FLAC, OggVorbis)):
        mapping = {
            "title": "TITLE",
            "artist": "ARTIST",
            "album": "ALBUM",
            "album_artist": "ALBUMARTIST",
            "year": "DATE",
            "original_year": "ORIGINALDATE",
            "track_number": "TRACKNUMBER",
            "musicbrainz_track_id": "MUSICBRAINZ_TRACKID",
            "musicbrainz_release_id": "MUSICBRAINZ_ALBUMID",
        }
        for field, vorbis_key in mapping.items():
            if field in new_tags and new_tags[field] is not None:
                audio[vorbis_key] = [str(new_tags[field])]
        audio.save()

    # 3. M4A / MP4
    elif isinstance(audio, MP4):
        if "title" in new_tags and new_tags["title"]:
            audio["\xa9nam"] = [str(new_tags["title"])]
        if "artist" in new_tags and new_tags["artist"]:
            audio["\xa9ART"] = [str(new_tags["artist"])]
        if "album" in new_tags and new_tags["album"]:
            audio["\xa9alb"] = [str(new_tags["album"])]
        if "album_artist" in new_tags and new_tags["album_artist"]:
            audio["aART"] = [str(new_tags["album_artist"])]
        if "year" in new_tags and new_tags["year"]:
            audio["\xa9day"] = [str(new_tags["year"])]
        if "track_number" in new_tags and new_tags["track_number"] is not None:
            audio["trkn"] = [(int(new_tags["track_number"]), 0)]
        audio.save()

    else:
        # Fallback generic save
        for k, v in new_tags.items():
            if v is not None:
                audio[k] = [str(v)]
        audio.save()

    return {
        "file_path": file_path,
        "status": "success",
        "backup_created": str(backup_path) if backup_path else None,
        "applied_diff": preview["diff"]
    }
