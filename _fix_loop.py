path = r'k:\dev\vibe-coding\musicbee-mcp-server\scripts\openrouter_agent_loop.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

insert_block = """# --------------------------------------------------------------------------- #
# Duplicate-sentence analysis (parallel overthinking guard)
# --------------------------------------------------------------------------- #


def _split_sentences(text):
    \"\"\"Split *text* into normalized sentences for duplicate detection.\"\"\"
    if not text:
        return []
    # Split on sentence-ending punctuation, keeping the delimiter.
    raw = re.split(r"(?<=[.!?])\\s+", str(text))
    sentences = []
    for chunk in raw:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Normalize: lowercase, collapse whitespace, strip trailing punctuation.
        normalized = re.sub(r"\\s+", " ", chunk.lower()).strip(" .!?")
        if normalized:
            sentences.append(normalized)
    return sentences


def detect_duplicate_sentences(text, min_sentence_length=8, duplicate_threshold=0.30):
    \"\"\"Analyze *text* for duplicate sentences.

    Returns a dict with:
        - ``total_sentences``: number of sentences found
        - ``unique_sentences``: number of distinct sentences
        - ``duplicate_count``: number of sentences that are duplicates
        - ``duplicate_ratio``: fraction of sentences that are duplicates
        - ``max_repeat``: maximum number of times any single sentence repeats
        - ``is_overthinking``: True when duplication exceeds threshold
        - ``repeated_sentences``: list of sentences repeated more than once
    \"\"\"
    sentences = _split_sentences(text)
    total = len(sentences)
    if total == 0:
        return {
            \"total_sentences\": 0,
            \"unique_sentences\": 0,
            \"duplicate_count\": 0,
            \"duplicate_ratio\": 0.0,
            \"max_repeat\": 0,
            \"is_overthinking\": False,
            \"repeated_sentences\": [],
        }

    # Filter out very short sentences (likely noise).
    meaningful = [s for s in sentences if len(s) >= min_sentence_length]
    if not meaningful:
        meaningful = sentences

    counts = {}
    for s in meaningful:
        counts[s] = counts.get(s, 0) + 1

    unique = len(counts)
    duplicate_count = sum(c - 1 for c in counts.values() if c > 1)
    duplicate_ratio = duplicate_count / len(meaningful) if meaningful else 0.0
    max_repeat = max(counts.values()) if counts else 0
    repeated = [s for s, c in counts.items() if c > 1]

    is_overthinking = (
        duplicate_ratio >= duplicate_threshold
        or max_repeat >= 3
        or (len(meaningful) >= 4 and duplicate_count >= 2)
    )

    return {
        \"total_sentences\": total,
        \"unique_sentences\": unique,
        \"duplicate_count\": duplicate_count,
        \"duplicate_ratio\": round(duplicate_ratio, 3),
        \"max_repeat\": max_repeat,
        \"is_overthinking\": is_overthinking,
        \"repeated_sentences\": repeated[:10],
    }


class DuplicateSentenceAnalyzer:
    \"\"\"Parallel analyzer that checks agent output for duplicate sentences.

    Runs ``detect_duplicate_sentences`` in a background thread so the main
    loop can submit text for analysis without blocking.  Results are
    retrieved via :meth:`result`.
    \"\"\"

    def __init__(self, text=\"\", max_workers=1):
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._future = None
        self._text = text
        if text:
            self.submit(text)

    def submit(self, text):
        \"\"\"Submit *text* for duplicate-sentence analysis.\"\"\"
        if self._future is not None and not self._future.done():
            self._future.cancel()
        self._text = text
        self._future = self._executor.submit(detect_duplicate_sentences, text)
        return self._future

    def result(self, timeout=None):
        \"\"\"Return the analysis result, waiting up to *timeout* seconds.\"\"\"
        if self._future is None:
            return detect_duplicate_sentences(self._text)
        try:
            return self._future.result(timeout=timeout)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            return detect_duplicate_sentences(self._text)

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown(wait=True)
        return False


def _run_duplicate_sentence_check(text):
    \"\"\"Convenience wrapper used by the parallel process path.\"\"\"
    return detect_duplicate_sentences(text)


"""

marker = 'def run_batch(tokens, model, api_key, max_turns, state, state_path,'
idx = content.find(marker)
if idx == -1:
    print('MARKER NOT FOUND')
else:
    new_content = content[:idx] + insert_block + content[idx:]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Inserted duplicate-sentence code before run_batch')
