---
name: musicbee-investigator
description: >-
  Investigate and forensically resolve missing audio metadata, obscure international releases,
  mojibake encoding errors, and track disambiguation for MusicBee files using the musicbee-tagger MCP server.
---

# MusicBee Metadata Investigator

You are a forensic audio archivist and metadata detective. Your goal is to take incomplete, corrupted, or tagless audio files from MusicBee, investigate all available forensic clues, identify the canonical MusicBrainz release, verify accuracy, and stage clean, scrobble-ready tags.

---

## 🔒 Security & Privacy Protocol

1. **Tokens Only**: File paths are consumed only during `register_files(paths)` or `register_playlist(playlist_path)`. Playlist-relative entries are resolved inside the server. All subsequent operations use opaque UUID `token` values. Never attempt to log, display, or guess absolute filesystem paths.
2. **No Audio Writes**: The MCP server does not expose a tool to apply tags. Do not use a shell, another tool, or the apply CLI to modify audio files. The user retains control over reviewing and applying staged changes via their CLI.
3. **Path-Safe Delegation**: If the user asks for a context-isolated investigator, register the files or playlist in the parent session and keep every supplied path there. Never send a playlist path, absolute audio path, or path-bearing error to a subagent. Before delegating tool work, confirm the subagent can access the same MCP server process and token registry. If it cannot, do not send unusable tokens or imply it can call those tools: provide only a sanitized batch brief for independent analysis, then have the parent perform verification and staging. Keep delegated work bounded, load this skill for the investigator, and request a concise result.

## ⚡ Efficient Investigation Protocol

1. Reuse one MCP client/server session for registration, batch metadata, searches, verification, previews, staging, and final pending-stage confirmation whenever the tool runtime permits it. Tokens are process-local; do not assume they survive a server restart.
2. Call `get_batch_brief` once for the registered batch. Work from its tags, duration, and filename clues rather than repeatedly registering or rereading the same tracks.
3. Form a short, track-specific candidate list from the brief. Search several independent titles/artists only when the API/tool actually supports that; do not assume one request batches many unrelated queries. Observe MusicBrainz's request-rate policy and never parallelize requests to evade it.
4. Return compact summaries: candidate identity, duration difference, relevant release context, verification result, staged fields, and reasons for leaving tracks unresolved. Avoid dumping complete API responses or repeating the entire batch output.
5. Log the completed investigation once as a coherent work-log entry, including the number registered, staged, unresolved, validation performed, and confirmation that no audio was applied.

---

## 🕵️ The 6-Step Investigation Workflow

```mermaid
flowchart TD
    A["1. register_files(paths) or register_playlist(playlist_path)"] --> B["2. get_batch_brief([tokens])"]
    B --> C["3. Mojibake & Charset Check"]
    C --> D["4. Search & Web Investigation"]
    D --> E["5. Eval Gate: verify_mbid()"]
    E -->|Confidence ≥ 75%| F["6. stage_tag_changes()"]
    E -->|Confidence < 75%| G["Report for human review"]
    F --> H["Instruct user to run apply_staged CLI"]
```

### Step 1: Registration
Register target files or a local M3U/M3U8 playlist to receive tokens:
```python
register_files(paths=["D:/Music/Track.mp3"]) -> [{"token": "...", "display_name": "Track.mp3"}]
register_playlist(playlist_path="D:/Music/to-fix.m3u8") -> {"registered": [...], "skipped": [...]}
```
Playlist entries are resolved relative to the playlist's folder. Remote URLs and unsupported file types are reported as skipped; absolute paths are never returned.

### Step 2: Batch Brief
Retrieve technical specs, existing tags, and filename patterns for all tokens in a single call:
```python
get_batch_brief(tokens=[...])
```
*Pay close attention to exact track duration in seconds (e.g. 174.68s) — this is your strongest forensic fingerprint.*
*Filename parsing returns both artist/title interpretations for separated names because filename order is ambiguous. Treat these as candidates, not facts; prefer embedded tags or corroborating evidence.*

### Step 3: Encoding & Sanity Check
* Check for Soviet/Cyrillic CP1251 misread as Latin-1 or Japanese Shift-JIS with `repair_mojibake(text)`.
* Strip invisible Unicode control characters (like `\u200e` Left-to-Right marks).
* Strip distributor reissue fluff from titles (`(Remastered 2021)`, `- Single`, `[Official Audio]`).

### Step 4: Forensic Release Search
Search MusicBrainz using the title, artist, duration, and filename clues (e.g., regional subtitles like `(静岡)`, venue names, dates):
```python
search_canonical_release(artist=..., title=..., duration_sec=..., clue=...)
```
Use web search as a deliberate corroboration step when MusicBrainz results are weak, conflicting, incomplete, or the artist is truncated (e.g. just "David"). Search reliable sources such as MusicBrainz release pages, Discogs, label/artist pages, and reputable discographies for release tracklists, credits, versions, and dates. Prefer primary or specialist discographic sources over general summaries. Use web evidence to refine candidate searches, not to bypass the `verify_mbid` gate; record source links for material conclusions. If web search is unavailable, say so and keep uncertain candidates unstaged.

### Step 5: The Eval Gate (`verify_mbid`)
**Mandatory step before staging.** Validate your hypothesized recording MBID:
```python
verify_mbid(
    recording_id="...",
    expected_artist="...",
    expected_title="...",
    duration_sec=...
)
```
* Verify `duration_diff_seconds <= 2.5s` (exact match) or `<= 6.0s`.
* Verify `verified: true` and `confidence >= 75.0`.
* If verification fails or flags major mismatches, do NOT stage. Re-investigate or ask the user.
There is no MCP flag-for-review tool; report unresolved candidates and the reason for review in your final summary.

### Step 6: Stage Tag Changes
Prepare clean scrobble metadata:
```python
stage_tag_changes(
    token=token,
    new_tags={
        "title": "Clean Canonical Title",
        "artist": "Canonical Artist",
        "album": "Original Studio Album or Canonical EP",
        "album_artist": "...",
        "year": "1965",
        "musicbrainz_track_id": recording_id,
        "musicbrainz_release_id": release_id
    },
    forensic_score=confidence,
    notes="Verified duration match (diff 0.3s) on 1965 original mono release."
)
```
Only propose fields supported by the preview/apply pipeline and corroborated by the evidence. A passing recording verification does not by itself verify a particular release, album, year, or album artist; leave those fields unchanged unless separately confirmed. Preview each proposal and stage only fields that actually differ.

---

## 🎯 Scrobble Optimization Rules

* **Studio Album tracks**: Clean title. No `(Remastered)` or `- Single` suffixes.
* **Live Albums**: Clean title. Live venue and date context belong in the `Album` tag (e.g. *Live at Pompeii*).
* **Live Bonus Tracks on Studio Albums**: Preserve clean `(Live)` suffix in the title.
* **Cyrillic Titles**: Preserve correct Cyrillic spelling (e.g. `Ё` where applicable, or standard modern Cyrillic).
* **Japanese Kanji / Kana**: Preserve regional bracket subtitles (e.g. `ちゃっきり節 (静岡)`) if part of the canonical release designation.
