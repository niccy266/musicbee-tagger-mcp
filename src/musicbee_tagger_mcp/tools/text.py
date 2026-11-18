"""Stateless text investigation tools."""

from typing import Any, Dict
import html
import re
import urllib.parse
import urllib.request

from ..error_codes import E_PROVIDER_FAILED, error_from_exception, make_error
from ..mojibake import fix_mojibake


def repair_mojibake(text: str) -> Dict[str, Any]:
    """Detect and suggest repairs for common mojibake patterns."""
    try:
        return fix_mojibake(text)
    except Exception as error:
        return error_from_exception(error, function="repair_mojibake")


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web for research clues about an artist, release, or track.

    Use for genre lookup or corroboration when MusicBrainz has no genre.
    NEXT STEP: Use the genre found here to include in stage_tag_changes.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "query is required"}
    if max_results < 1:
        max_results = 5
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as error:
        return make_error(
            E_PROVIDER_FAILED,
            f"web search failed: {type(error).__name__}",
            function="web_search",
        )

    results = []
    for match in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        body,
        re.S,
    ):
        href, title, snippet = match.groups()
        parsed = urllib.parse.urlparse(href)
        params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in params:
            href = params["uddg"][0]
        title = re.sub(r"<[^>]+>", "", html.unescape(title)).strip()
        snippet = re.sub(r"<[^>]+>", "", html.unescape(snippet)).strip()
        if title or href:
            results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return {"query": query, "results": results}


def register_text_tools(app) -> None:
    app.tool()(repair_mojibake)
    app.tool()(web_search)
