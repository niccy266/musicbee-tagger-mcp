# Audit Findings – Session Cache & Tag Staging Verification

**Branch:** cline/stage-verification-and-job-cache (HEAD 9fd496e)
**Date:** 2026-11-19

## Executive Reality Check
- Git state verified: clean working tree on cline/stage-verification-and-job-cache, pushed to origin/cline/stage-verification-and-job-cache.
- Default branch is master; feature branch exists alongside.
- **Critical finding:** The installed MCP SDK (mcp v2.3.0) defines ServerSession as per-request proxy built once per inbound request. Its __init__ signature (request_outbound, connection, *, request_meta=None), no __slots__, __weakrefoffset__ = -32 -> weakref-able. Therefore the WeakKeyDictionary cache keyed by session is useless across requests because each call gets a fresh object; entries vanish on GC. Tests pass only because they reuse _FakeSession instances.
- Prior report's claim (real sessions aren't weakref-able) is false.

## Bug #1 (WeakKeyDictionary Silent Failure)
- Location: src/musicbee_tagger_mcp/session_cache.py lines 13, 36, 48.
- Problem: remember_job_id() stores session -> job_id in WeakKeyDictionary(). If session isn't weakly referenceable, TypeError is caught silently and ignored.
- Why it fails: Built-in types (object, SimpleNamespace) raise TypeError when added to WeakKeyDictionary. Real ServerSession objects ARE weakref-able, so this never triggers in practice; the silent swallow means caching never happens.
- Impact: Job-id caching disabled server-side; agents must pass job_id every call.

## Bug #2 (Whitespace job_id Fallback)
- resolve_job_id("   ", ctx) returns previously cached id instead of erroring.
- Because blank ids are treated as omit, the function falls back to recall value without calling remember_job_id. This masks bad input.

## Bug #3 (Insufficient Test Coverage)
- Tests use _FakeSession (plain class) and _FakeContext (SimpleNamespace); both are weakly-referenceable, masking real-world failure.
- Missing coverage: non-weakref-able session types, whitespace rejection, isolation between connections, end-to-end multi-request calls.

## Dead / Unreferenced Code
- manual_* aliases in playlists.py (lines 47-72).
- Ordering wrapper loop in playlists.py (lines 140-209).
- Forwarder methods in stage_manifest_store.py (list_stages, search, etc.).
- Aliases in scripts/openrouter_agent_loop.py (~20 unused functions).
- Duplicate skill copies in .agents/skills/... and release/...

## Missing Features & Inefficiencies
- list_staged_changes() with no filters returns first manifest by filename, not newest stage.
- Unknown kwargs silently dropped.
- verified tautology.
- No public active job view.
- Disk reads of all JSON manifests per call (O(n)).

## Revised Plan (no edits yet)
1. Replace CRITICAL_BUGS_REPORT.md with corrected version.
2. Decide caching strategy: (A) connection-scoped cache using stable handle from context.request_context.session._connection; or (B) drop server-side caching entirely and require explicit job_id each call.
3. Fix validation errors to return make_error(E_INVALID_INPUT, ...). Update tool schemas.
4. Sort list_staged_changes results by created_at desc, limit=1 default.
5. Add comprehensive async tests with real ServerSession lifecycle.
6. Rebuild container after tests pass.

## Open Questions
- Does context.request_context.session._connection give a stable per-connection handle?
- Is genre a valid tag field?
- Which tool name did chat agent invoke (stage_tag_changes vs musicbee_stage_tag_changes)?
- Is niccy266/musicbee-tagger-mcp a public GitHub repo?

---
*Prepared 2026-11-19 by Cline.*