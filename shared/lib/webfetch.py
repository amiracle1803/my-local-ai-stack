"""
webfetch.py  --  Turn a web page URL into clean text/markdown.

Default engine: trafilatura. It installs cleanly on Windows from a wheel, needs
no browser, and is very good at pulling the actual article out of a page
(stripping nav bars, ads, boilerplate).

Optional upgrade: crawl4ai (JavaScript-heavy sites). It's heavier and needs a
headless browser, so we only import it if it's installed AND requested. If it
isn't available we silently fall back to trafilatura, so nothing breaks.

This helper is used by Project 1 (research tasks with URLs) and Project 3
(research feeds).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FetchResult:
    url: str
    title: str
    text: str
    ok: bool
    engine: str = "trafilatura"
    error: str = ""


def _fetch_trafilatura(url: str) -> FetchResult:
    import trafilatura  # lazy import: base dependency
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return FetchResult(url, "", "", ok=False, error="could not download page")
    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    ) or ""
    title = ""
    try:
        meta = trafilatura.extract_metadata(downloaded)
        if meta and meta.title:
            title = meta.title
    except Exception:  # noqa: BLE001
        pass
    ok = bool(text.strip())
    return FetchResult(url, title, text, ok=ok,
                       error="" if ok else "no article text extracted")


def _fetch_crawl4ai(url: str) -> FetchResult | None:
    """Return a FetchResult using crawl4ai, or None if it isn't installed."""
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except Exception:  # noqa: BLE001 - not installed / import error
        return None

    async def _run():
        async with AsyncWebCrawler() as crawler:
            res = await crawler.arun(url=url)
            return res

    try:
        res = asyncio.run(_run())
        md = getattr(res, "markdown", "") or ""
        title = ""
        meta = getattr(res, "metadata", None) or {}
        if isinstance(meta, dict):
            title = meta.get("title", "") or ""
        ok = bool(md.strip())
        return FetchResult(url, title, md, ok=ok, engine="crawl4ai",
                           error="" if ok else "no markdown produced")
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url, "", "", ok=False, engine="crawl4ai", error=str(exc))


def fetch_clean(url: str, prefer_crawl4ai: bool = False) -> FetchResult:
    """
    Fetch a URL and return clean text. Tries crawl4ai only if you ask for it
    AND it's installed; otherwise (and on any failure) uses trafilatura.
    """
    if prefer_crawl4ai:
        result = _fetch_crawl4ai(url)
        if result is not None and result.ok:
            return result
        # fall through to trafilatura on miss/failure

    try:
        return _fetch_trafilatura(url)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url, "", "", ok=False, error=f"fetch failed: {exc}")
