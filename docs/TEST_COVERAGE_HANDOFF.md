# Test coverage handoff

Written 2026-11-14 at master `7e60c8c`, when the coverage gate became the only
red check. This document exists so test work can be handed to another agent
without re-discovering the environment, the conventions, or the traps.

## 1. Where the number stands

| Metric | Value |
| --- | --- |
| Statements | 6,218 |
| Covered | 3,478 |
| Missed | 2,740 |
| Coverage | **56%** |
| `fail_under` | **56** (temporary floor, `pyproject.toml`) |
| Target | **73** |
| Gap | **+1,061 covered statements** |
| Suite | 290 passed, 2 skipped, ~29 s |

The 73% gate arrived with issue #66 *after* the last green run, so it has never
passed. That is not a merge regression: several modules reached master without
unit tests at all.

**Never lower `fail_under`.** Raise it in the same PR that adds the coverage.
A single run tells you the exact figure:

```bash
python -m pytest -q --cov --cov-report=term-missing
```

Suggested ratchet: 56 → 60 → 65 → 70 → 73.

## 2. Ground rules

- CI is the gate: `pytest` on 3.11, 3.12 and 3.14 with `--cov`, plus
  `pylint --recursive=y --errors-only src`, a lint score, a dependency audit and
  a Windows MCPB build. All must stay green.
- Branch per issue, per `AGENTS.md`: `<agent>/issue-<n>-<slug>`, PR into master.
  Do not push feature work straight to master.
- **Offline by default.** `tests/conftest.py` replaces `socket.socket`,
  `socket.create_connection` and `urllib.request.urlopen` with raisers unless the
  test carries `@pytest.mark.network`. Monkeypatch the client instead of using
  the marker; only the marker makes a real call, and those tests are flaky in CI.
- **Deterministic tests only.** No `sleep`, no wall-clock dependence, no real
  HTTP, no ffmpeg unless marked `requires_audio_fixtures`.
- Markers are strict — `--strict-markers` fails an unknown marker.
- `-W error::DeprecationWarning:musicbee_tagger_mcp` is armed: a deprecation
  warning raised *from this package* fails the test. Fix the source, do not
  filter the warning.
- Per-test timeout is 120 s (`--timeout=120`).

## 3. Fixtures you already have

`tests/conftest.py` gives you, automatically:

| Fixture | Effect |
| --- | --- |
| `isolate_app_data` (autouse) | Points `MUSICBEE_TAGGER_DATA_DIR`, `HOME` and `APPDATA` at `tmp_path`; resets the `file_registry`, `review_flags`, `staging`, `staged_apply` singletons; **asserts** nothing was written to the real home directory |
| `block_network_access` (autouse) | Blocks sockets and `urlopen`, except from asyncio/anyio/selectors internals |
| `protect_tracked_audio_fixtures` (autouse) | Hashes `test_files/test_audio_files` before and after; fails the test if it modified a fixture |
| `tmp_path` | Use it for every file you create. Never write into the repo. |

If you introduce a **new module-level singleton**, add it to the reset list in
`isolate_app_data` or your tests will leak state into each other. That leak is
what previously made `test_list_jobs_returns_path_free_available_summaries`
fail locally but pass in CI.

## 4. Priority queue

Ordered by statements gained per unit of effort. Cover the top seven and the
target is met with room to spare.

| # | Module | Stmts | Missed | Now | Suggested file | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `job_store.py` | 1,212 | 615 | 49% | `tests/test_job_store.py` | Pure logic + JSON persistence. Highest yield in the repo. |
| 2 | `lastfm.py` | 572 | 406 | 29% | `tests/test_lastfm.py` | Many pure helpers; network paths take a monkeypatched `_get_client`. |
| 3 | `review_flags.py` | 281 | 223 | 21% | `tests/test_review_flags.py` | Store CRUD + persistence. |
| 4 | `stage_manifest_store.py` | 233 | 132 | 43% | `tests/test_stage_manifest_store.py` | Manifest read/write, versioning. |
| 5 | `staged_audit.py` | 136 | 126 | 7% | `tests/test_staged_audit.py` | Backs the `audit_staged_changes` tool. Currently near-untested. |
| 6 | `staging.py` | 295 | 107 | 64% | extend `test_staged_change_controls.py` | Paths not yet covered: amend/withdraw edge cases. |
| 7 | `genre_cleanup.py` | 129 | 98 | 24% | `tests/test_genre_cleanup.py` | Pure functions — easy wins. |
| 8 | `tools/musicbrainz.py` | 93 | 69 | 26% | `tests/test_tools_musicbrainz.py` | Tool wrappers; assert returned payloads. |
| 9 | `file_registry.py` | 272 | 78 | 71% | extend `test_file_registry_*` | Remaining error branches. |
| 10 | `musicbrainz_verification.py` | 161 | 62 | 61% | `tests/test_musicbrainz_verification.py` | Scoring paths. |

Cheap extra: **17 alias modules sit at 0%** (`lastfm_client.py`,
`acoustid_client.py`, `acrcloud_provider.py`, `genre.py`, `genres.py`,
`fingerprint.py`, …). Each is a one-line `from .real import *` shim. A single
parametrised test that imports every one of them and asserts a known symbol is
exposed takes them all to 100% and would catch a broken alias after a rename.
One small test, ~17 statements, plus real regression value.

## 5. Module-specific guidance

### `lastfm.py`
Split it in two passes. First the **pure** helpers, which need no mocking:
`split_equals_halves`, `has_cyrillic`, `strip_invisible`, `should_keep_cyrillic`,
`filter_variants`, `contains_variant_word`, `is_excluded_variant`,
`parse_sidecar_pairs`, `folder_hints_as_evidence`, `folder_evidence_weighted`,
`rank_candidates`, `transliterate`. Second the client-bound functions
(`lastfm_track_search`, `lastfm_track_get_info`, `web_search_fallback`), which
should be driven through a fake client object injected by monkeypatching
`_get_client`.

Two functions are **dead code** — defined and never called anywhere in `src/` or
`tests/`: `cyrillic_policy` (line 102) and `exclude_variant` (line 138). Do not
spend effort testing them. Either delete them or document why they stay; raising
coverage on unused code is the wrong trade.

### `job_store.py`
The highest-value target and the one with real bug history. Cover:
- creation and every status transition, including invalid transitions;
- `list_jobs()` — assert a 3-track job appears **once**, not three times, and
  that every job is listed, not just the first. Both were genuine merge
  regressions;
- the cross-job duplicate policy in `add_track` (a track rejected because it is
  already in another job);
- `set_skipped` persisting to disk, not only to the in-memory dict;
- reload from disk in a fresh instance (proves persistence rather than state).

### `staged_audit.py` and `staging.py`
These back the review tools. Assert on the **returned status**, not just on the
manifest flag. The original defect was `StagedChangeApplier.apply()` setting
`applied = True` unconditionally, so a no-op run reported success and staged
changes read as "done" while nothing was written. A test that only checks
`manifest["applied"]` would have passed that bug happily.

### `genre_cleanup.py`
Cover the pure cleaning functions and the `_clean_genre_clutter` alias used by
the tool wrapper. There was a recursion bug here: the wrapper shadowed the
imported helper and then called it on a genre *string*, re-entering itself and
iterating the characters of the string as track tokens. A test that passes
`"Pop; Rock"` and asserts the output is a cleaned genre string — not a dict, not
per-character results — locks that shut.

## 6. Traps specific to this repo

1. **Two exhaustive tool pins.** `tests/test_secure_pipeline.py` asserts the
   exact registered tool set, and `tests/test_release_assets.py` asserts the MCPB
   manifest's tool list. Adding one tool means updating both. A third test now
   asserts manifest ⊆ registry, so a manifest advertising a dropped tool fails
   loudly. Do not weaken these to subsets — they are the only thing stopping a
   tool from silently disappearing from the release.
2. **Duplicate registration is possible and quiet.** `flag_for_review` was once
   imported twice and registered twice; it only warned at import. If you touch
   `tools/__init__.py`, assert the registered count equals the intended count.
3. **Bad merge resolutions are this repo's number-one defect source.** Six
   separate faults in one session came from merges taking both sides of a
   conflict: duplicated methods in `job_store.py`, `verify_mbid` defined twice,
   a loop nested inside a loop in `list_jobs`, telescoped duplicate parameters.
   When you resolve a conflict in this repo, read the *function body*, not just
   the marker region.
4. **No process substitution.** Bash `/dev/fd` is unavailable on the machine this
   was developed on; `<(cmd)` fails silently. Use temp files in shell helpers.
5. **Disc quota is 1 GB** on the dev machine. Pytest temp roots reached 871 MB
   during a single run. On that machine, prefer CI; elsewhere, point `TMPDIR` at
   a roomy path.

## 7. Definition of done, per PR

- [ ] New tests target one module (keeps review and conflicts manageable).
- [ ] `python -m pytest -q --cov --cov-report=term-missing` passes locally.
- [ ] Coverage figure went **up**; `fail_under` raised to the new floor in the
      same commit.
- [ ] No test depends on wall-clock time, real network, or the real home dir.
- [ ] No existing test was weakened, skipped, or deleted to make the number move.
- [ ] `pylint --recursive=y --errors-only src` still clean.
- [ ] `WORK_LOG.md` has an entry, in the style of the existing ones.
- [ ] CI green on all three Python versions plus release checks.
