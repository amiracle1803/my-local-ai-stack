"""
fetch_article.py  --  Thin wrapper so Project 3 scripts have a local import for
                      fetching a URL as clean text.

The real logic lives in shared/lib/webfetch.py (shared with Project 1). This
just re-exports it. Run directly to test a single URL:

    python fetch_article.py https://example.com/some-article
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.lib.webfetch import fetch_clean, FetchResult  # noqa: E402,F401

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    r = fetch_clean(url)
    print(f"ok={r.ok} engine={r.engine} title={r.title!r} error={r.error}")
    print("-" * 60)
    print((r.text or "")[:2000])
