"""Stateless text investigation tools."""

from typing import Any, Dict
import html
import re
import urllib.parse
import urllib.request

from ..mojibake import fix_mojibake


def repair_mojibake(text: str) -> Dict[str, Any]:
    """Detect and suggest repairs for common mojibake patterns."""
    return fix_mojibake(text)


def web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Search the web for research clues about an artist, release, or track."""
    query = (query or "").strip()
    if not query:
        return {"error": "query is required"}
    if max_results < 1:
        max_results = 5
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MusicBeeTagger/1.0)"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as error:
        return {"error": f"web search failed: {type(error).__name__}: {error}"}

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
