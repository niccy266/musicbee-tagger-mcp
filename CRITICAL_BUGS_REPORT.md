# Critical Bugs Report: Stage Verification & Job Caching
**Branch:** `cline/stage-verification-and-job-cache`  
**Commit:** `08ae71c` (feat: verify staging writes and remember job ids per connection)  
**Status:** ✅ Bugs #1 and #2 fixed in the merge commit (see bottom); Bug #3 partially addressed by the new regression tests.  
**Tests:** 10/10 pass (but tests are insufficient to catch bugs)

---

## Executive Summary

The session's implementation introduced **three critical bugs** that will cause:
1. **Silent data loss** when agents stage changes on connections using certain MCP server configurations
2. **Job ID cache failures** that silently revert to old jobs instead of raising errors
3. **Insufficient test coverage** that masks these failures

**Root Cause:** The WeakKeyDictionary job-id caching mechanism assumes all MCP ServerSession objects are weakly-referenceable class instances, but doesn't validate this assumption or fall back gracefully. The tests use custom `_FakeSession` classes which ARE weakly-referenceable, masking the real-world failure.

---

## 🔴 Bug #1: WeakKeyDictionary Silent Failure (Critical)

**Location:** `src/musicbee_tagger_mcp/session_cache.py` lines 13, 36, 48

**Problem:**
```python
_ACTIVE_JOB_IDS: "WeakKeyDictionary[Any, str]" = WeakKeyDictionary()

def remember_job_id(job_id: Optional[str], context: Any = None) -> None:
    if not isinstance(job_id, str) or not job_id.strip():
        return
    session = _session_for(context)
    if session is None:
        return
    try:
        _ACTIVE_JOB_IDS[session] = job_id.strip()  # ← Line 36
    except TypeError:
        return  # ← SILENT FAILURE: TypeError is swallowed
```

**Why It Fails:**
- Not all MCP ServerSession objects can be weakly referenced.
- Built-in types (`object`, `SimpleNamespace`, some MCP implementations) raise `TypeError: cannot create 'weakref' to '...' object` when added to WeakKeyDictionary.
- The `except TypeError: return` silently ignores this failure.
- **Result:** `remember_job_id()` appears to succeed but doesn't actually cache anything. Subsequent `recall_job_id()` calls return `None`.
- Agents then fall back to requiring explicit `job_id` on every call, defeating the caching feature entirely.

**Evidence:**
```python
from weakref import WeakKeyDictionary
wkd = WeakKeyDictionary()

# This fails silently:
plain_obj = object()
wkd[plain_obj] = 'value'  # TypeError: cannot create 'weakref' to 'object' object
# In session_cache.py, this exception is caught and suppressed.

# Tests use custom classes, which CAN be weakly referenced:
class _FakeSession:
    pass
# _FakeSession instances ARE weakly-referenceable, so tests pass.
```

**Impact:** 
- 🔴 **High**: Any MCP client/session implementation that doesn't use custom classes will silently lose job-id caching.
- Job-id caching feature is completely disabled without raising an error.

**Fix Strategy:**
Replace `WeakKeyDictionary` with a **ContextVar-based** approach (async-safe, recommended) or a **registry-based session ID** (use `id(session)` as key).




---

## 🔴 Bug #2: job_id Whitespace Handling Inconsistency (Critical)

**Location:** `src/musicbee_tagger_mcp/session_cache.py` lines 64–75

**Problem:**
```python
def resolve_job_id(
    job_id: Optional[str] = None, context: Any = None
) -> Optional[str]:
    if isinstance(job_id, str) and job_id.strip():
        resolved = job_id.strip()
        remember_job_id(resolved, context)  # ← Caches the stripped value
        return resolved
    return recall_job_id(context)  # ← Falls back to cached value
```

**Why It Fails:**
- If a tool is called with `job_id="   "` (whitespace-only), the condition `job_id.strip()` evaluates to `False`.
- The function **does NOT call** `remember_job_id()` and **does NOT clear** the old cached value.
- It instead returns the **previously cached job_id** (from a different call or session).
- This silent fallback masks errors that should be caught during tool invocation.

**Impact:**
- 🔴 **High**: Agents accidentally passing blank job_id (typo, variable binding) will silently reuse an old job id.
- Cross-playlist contamination: batches tagged with incorrect job metadata.

**Fix Strategy:**
When `job_id` is empty/whitespace string, **raise ValueError** instead of silently falling back:
```python
if isinstance(job_id, str):
    stripped = job_id.strip()
    if not stripped:
        raise ValueError(
            "job_id cannot be empty or whitespace-only. "
            "Omit it to use the cached job or pass a valid uuid."
        )
    remember_job_id(stripped, context)
    return stripped
return recall_job_id(context)
```


---

## Remediation Plan (For Next Session)

### Phase 1: Root Cause Analysis & Validation (1–2 hours)
1. **Confirm Bug #1 severity:**
   - Query the actual MCP server implementation in the running container.
   - Test if real `ServerSession` objects are weakly-referenceable.
   - If not: session caching is **completely non-functional** in production.

2. **Confirm Bug #2 trigger:**
   - Check if agents/clients can pass whitespace job_id (through typo or variable binding).
   - Verify that silent fallback actually occurs (not caught by tools).

### Phase 2: Choose Caching Strategy (1–2 hours)

**Option A: ContextVar (Recommended for Async MCP)**
```python
from contextvars import ContextVar

_ACTIVE_JOB_ID: ContextVar[Optional[str]] = ContextVar('active_job_id', default=None)

def remember_job_id(job_id: Optional[str], context: Any = None) -> None:
    if not isinstance(job_id, str) or not job_id.strip():
        return
    _ACTIVE_JOB_ID.set(job_id.strip())

def recall_job_id(context: Any = None) -> Optional[str]:
    return _ACTIVE_JOB_ID.get()
```
- ✅ Works with any MCP implementation.
- ✅ Automatically isolated per async task.
- ✅ No manual cleanup needed.
- Recommended: MCP server is async Python.

**Option B: Registry-Based (Identity as Key)**
```python
_ACTIVE_JOB_IDS: Dict[int, str] = {}  # {id(session): job_id}

def remember_job_id(job_id: Optional[str], context: Any = None) -> None:
    if not isinstance(job_id, str) or not job_id.strip():
        return
    session = _session_for(context)
    if session is None:
        return
    _ACTIVE_JOB_IDS[id(session)] = job_id.strip()
```
- ✅ Works with any object type (no weakref constraint).
- ⚠️ Requires manual cleanup to prevent memory leaks.

**Recommendation:** Use **ContextVar** (Option A). It is simpler, async-safe, and requires no cleanup.

### Phase 3: Fix Bugs (2–3 hours)

1. **Replace `session_cache.py`:**
   - Rewrite using ContextVar.
   - Remove WeakKeyDictionary.
   - Raise `ValueError` for empty job_id.

2. **Update error messages in tools.**

3. **Update SKILL.md** to reflect reliable caching.

### Phase 4: Expand Test Coverage (2–3 hours)

1. **Add async tests for ContextVar isolation.**
2. **Add tests for whitespace rejection.**
3. **Add integration tests** with real MCP server context.
4. **Target 100% coverage** on `session_cache.py`.

### Phase 5: Integration Test & Container Rebuild (1–2 hours)

1. **Build and test locally:**
   ```bash
   docker compose build musicbee-mcp
   docker compose up -d musicbee-mcp
   ```

2. **Run full test suite:**
   ```bash
   pytest tests/ -x --tb=short
   ```

3. **Smoke test via agent:**
   - Register small playlist.
   - Call `list_jobs`.
   - Call `next_batch` with explicit `job_id`.
   - Call `next_batch` with omitted `job_id` (should use cache).
   - Verify correct job is used in staged changes.

### Phase 6: Commit & PR (30 mins)

1. **Commit on the same branch:**
   ```bash
   git add -A
   git commit -m "fix: replace WeakKeyDictionary with ContextVar for job_id caching; add comprehensive tests"
   ```

2. **Push and open PR.**

---

## Files Requiring Changes

| File | Change | Priority |
|------|--------|----------|
| `src/musicbee_tagger_mcp/session_cache.py` | Replace WeakKeyDictionary with ContextVar; add input validation | 🔴 Critical |
| `tests/test_stage_verification_and_job_cache.py` | Add async tests, whitespace rejection, isolation tests | 🔴 Critical |
| `src/musicbee_tagger_mcp/tools/playlists.py` | Update error messages if validation changes | 🟡 Minor |
| `src/musicbee_tagger_mcp/tools/tags.py` | Update error messages if validation changes | 🟡 Minor |

---

## Verification Checklist (For Next Session)

- [ ] Confirm MCP server's actual ServerSession implementation.
- [ ] Reproduce Bug #1 with real ServerSession (or confirm it doesn't apply).
- [ ] Reproduce Bug #2 with whitespace job_id input.
- [ ] Implement ContextVar-based caching.
- [ ] Validate whitespace handling raises clear error.
- [ ] Add comprehensive async tests.
- [ ] Run full pytest suite: all tests pass.
- [ ] Run pytest with coverage: session_cache.py at 100%.
- [ ] Build container and verify schemas exposed.
- [ ] Manual smoke test with small playlist.
- [ ] Commit, push, prepare PR.

---

## Notes for Next Agent

1. **This branch IS committed and pushed.** Start at Phase 1 (Root Cause Validation).

2. **Tests pass, but bugs exist.** Bugs 1 & 2 are masked by using `_FakeSession` (a custom class that IS weakly-referenceable).

3. **Choose ContextVar.** It is the simplest, most robust solution for async Python servers.

4. **Whitespace validation is non-negotiable.** Must raise `ValueError`, not silently fall back.

5. **Comprehensive tests are mandatory.** Before declaring this fixed, add tests for:
   - Multiple independent sessions (isolation).
   - Whitespace rejection.
   - Graceful degradation (no context).
   - End-to-end tool calls across requests.

6. **Document the final choice** in `src/musicbee_tagger_mcp/session_cache.py` docstring.

---

**Status:** 🟡 Branch pushed, bugs identified, plan prepared. Ready for next session.


---

## 🔴 Bug #3: Insufficient Verification Test Coverage (Critical)

**Location:** `tests/test_stage_verification_and_job_cache.py`

**Problem:**
Tests use `_FakeSession` (a custom class that IS weakly-referenceable), masking the real-world failure where real MCP ServerSession objects may NOT be weakly-referenceable.

**Missing Tests:**
1. ✗ Verify that caching works with non-weakref-able session types.
2. ✗ Verify that **whitespace-only job_id** raises an error.
3. ✗ Verify that multiple *independent* sessions do NOT cross-contaminate cached job_ids.
4. ✗ End-to-end test: tool calls across multiple MCP requests with omitted job_id.

**Impact:**
- 🔴 **High**: Bugs 1 & 2 are masked by insufficient tests.

**Fix Strategy:**
Replace tests with ContextVar-based caching (which requires async tests), add isolation tests, whitespace rejection tests.



---

## Resolution (2026-11-19, merge session)

- **Bug #1 fixed** without abandoning weakrefs: unweakrefable sessions now fall
  back to a bounded `OrderedDict` keyed by `id(session)` (limit 64, LRU
  eviction). No silent data loss; no unbounded growth.
- **Bug #2 fixed**: `resolve_job_id` now raises `ValueError` on a
  whitespace-only `job_id` instead of silently reusing the remembered job.
- Regression tests added to `tests/test_stage_verification_and_job_cache.py`
  (unweakrefable session round-trip, cache bound, blank job_id rejection).
