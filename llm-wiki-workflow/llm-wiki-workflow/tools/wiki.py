#!/usr/bin/env python3
"""
wiki.py - deterministic tooling for the LLM Wiki workflow.

This handles the mechanical, non-AI parts of the workflow so they are
reliable and repeatable:

    init     scaffold a new wiki project
    new      create a page with valid frontmatter
    index    regenerate wiki/index.md from page frontmatter
    lint     health-check the wiki (schema, links, sources, staleness)
    log      append a timestamped entry to wiki/log.md
    search   find pages by keyword (helps the query workflow)

The AI parts (summarizing sources, synthesizing answers, deciding what a
page should say) stay with the agent and are governed by CLAUDE.md.

No third-party dependencies. Python 3.8+.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema constants (mirror CLAUDE.md)
# ---------------------------------------------------------------------------

PAGE_TYPES = ("concept", "entity", "source-summary", "comparison", "overview", "log")
CONFIDENCE = ("high", "medium", "low")
REQUIRED_FIELDS = ("title", "type", "created", "updated")

# friendly `new` subtype -> (frontmatter type, wiki subfolder)
NEW_KINDS = {
    "concept": ("concept", "concepts"),
    "entity": ("entity", "entities"),
    "source": ("source-summary", "sources"),
    "comparison": ("comparison", "comparisons"),
}

# files under wiki/ that are structural, not content pages
STRUCTURAL = {"index.md", "log.md", "overview.md"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def today() -> str:
    return datetime.date.today().isoformat()


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def find_root(explicit=None) -> Path:
    """Locate the wiki root: nearest ancestor (incl. cwd) containing wiki/."""
    if explicit:
        root = Path(explicit).resolve()
        if not (root / "wiki").is_dir():
            sys.exit(f"error: --root {root} has no wiki/ directory")
        return root
    here = Path.cwd().resolve()
    for cand in [here, *here.parents]:
        if (cand / "wiki").is_dir():
            return cand
    sys.exit(
        "error: not inside a wiki project (no wiki/ directory found).\n"
        "       run this from the project root, or pass --root PATH,\n"
        "       or create one with:  python3 tools/wiki.py init <name>"
    )


# ---------------------------------------------------------------------------
# Frontmatter parsing / serialization
#
# The schema uses a constrained subset of YAML:
#   key: scalar
#   key:
#     - list item
#     - list item
# We parse exactly that, and report anything malformed as a lint error
# rather than guessing.
# ---------------------------------------------------------------------------

class FMError(Exception):
    pass


def parse_frontmatter(text: str):
    """Return (meta: dict, body: str). Raises FMError if frontmatter is bad."""
    if not text.startswith("---"):
        raise FMError("missing frontmatter (file must start with '---')")

    lines = text.splitlines()
    # find closing '---'
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise FMError("frontmatter not closed (no second '---')")

    meta = {}
    i = 1
    while i < end:
        raw = lines[i]
        stripped = raw.strip()
        if stripped == "" or stripped.startswith("#"):
            i += 1
            continue
        if raw.startswith((" ", "\t")) or stripped.startswith("- "):
            raise FMError(f"unexpected indentation at frontmatter line {i}: {raw!r}")
        if ":" not in stripped:
            raise FMError(f"expected 'key: value' at frontmatter line {i}: {raw!r}")

        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if val == "" or val == "[]":
            # either an empty value or the start of a block list
            items = []
            j = i + 1
            while j < end:
                nxt = lines[j]
                ns = nxt.strip()
                if ns == "":
                    j += 1
                    continue
                if nxt.startswith((" ", "\t")) and ns.startswith("- "):
                    items.append(_unquote(ns[2:].strip()))
                    j += 1
                else:
                    break
            meta[key] = items
            i = j
        else:
            meta[key] = _unquote(val)
            i += 1

    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


def _unquote(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def serialize_frontmatter(meta: dict) -> str:
    """Write frontmatter in canonical schema order."""
    order = ["title", "type", "sources", "related", "created", "updated", "confidence"]
    out = ["---"]
    for key in order:
        if key not in meta:
            continue
        val = meta[key]
        if isinstance(val, list):
            out.append(f"{key}:")
            for item in val:
                out.append(f"  - {item}")
        else:
            out.append(f"{key}: {val}")
    out.append("---")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Page model
# ---------------------------------------------------------------------------

class Page:
    def __init__(self, path: Path, root: Path):
        self.path = path
        self.root = root
        self.rel = path.relative_to(root).as_posix()           # e.g. wiki/concepts/x.md
        self.wiki_rel = path.relative_to(root / "wiki").as_posix()  # e.g. concepts/x.md
        self.error = None
        self.meta = {}
        self.body = ""
        try:
            self.meta, self.body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except FMError as e:
            self.error = str(e)
        except UnicodeDecodeError:
            self.error = "file is not valid UTF-8 text"

    @property
    def type(self):
        return self.meta.get("type")

    def summary(self) -> str:
        """One-line summary for the index: explicit `summary` field, else first body line."""
        if isinstance(self.meta.get("summary"), str) and self.meta["summary"].strip():
            return self.meta["summary"].strip()
        for line in self.body.splitlines():
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("<!--"):
                return (s[:117] + "...") if len(s) > 120 else s
        return self.meta.get("title", self.wiki_rel)

    def link_targets(self):
        """All wiki pages this page references, as wiki-relative paths (no extension)."""
        targets = set()
        for ref in self.meta.get("related", []) or []:
            targets.add(_normalize_link(ref))
        for m in WIKILINK_RE.findall(self.body):
            targets.add(_normalize_link(m))
        return targets


def _normalize_link(ref: str) -> str:
    """Normalize a related/wikilink reference to wiki-relative path without extension."""
    ref = ref.strip()
    # accept anchor / display syntax: [[path|label]] or path#section
    ref = ref.split("|", 1)[0].split("#", 1)[0].strip()
    for prefix in ("wiki/", "./", "/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    if ref.endswith(".md"):
        ref = ref[:-3]
    return ref


def load_pages(root: Path):
    wiki = root / "wiki"
    pages = []
    for path in sorted(wiki.rglob("*.md")):
        if path.name in STRUCTURAL and path.parent == wiki:
            continue
        pages.append(Page(path, root))
    return pages


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args):
    root = Path(args.path).resolve()
    if root.exists() and any(root.iterdir()):
        sys.exit(f"error: {root} already exists and is not empty")

    dirs = [
        "raw/articles", "raw/papers", "raw/repos", "raw/data", "raw/images", "raw/assets",
        "wiki/concepts", "wiki/entities", "wiki/sources", "wiki/comparisons",
        "tools",
    ]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
        if d.startswith("raw/"):
            (root / d / ".gitkeep").write_text("", encoding="utf-8")

    (root / "wiki/index.md").write_text("# Wiki Index\n\n_(empty — run `wiki index` after adding pages)_\n", encoding="utf-8")
    (root / "wiki/log.md").write_text("# Activity Log\n", encoding="utf-8")
    (root / "wiki/overview.md").write_text(
        serialize_frontmatter({
            "title": "Overview",
            "type": "overview",
            "sources": [],
            "related": [],
            "created": today(),
            "updated": today(),
            "confidence": "low",
        }) + "\n\n# Overview\n\nHigh-level synthesis of this topic. Fill in as the wiki grows.\n",
        encoding="utf-8",
    )
    # copy this very script into the new project so it is self-contained
    (root / "tools/wiki.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"initialized wiki project at {root}")
    print("next: add a source under raw/, then `python3 tools/wiki.py new source <slug>`")


def cmd_new(args):
    root = find_root(args.root)
    fmtype, folder = NEW_KINDS[args.kind]
    slug = slugify(args.slug)
    if not slug:
        sys.exit("error: slug is empty after slugifying")
    dest = root / "wiki" / folder / f"{slug}.md"
    if dest.exists():
        sys.exit(f"error: {dest.relative_to(root)} already exists")

    title = args.title or slug.replace("-", " ").title()
    meta = {
        "title": title,
        "type": fmtype,
        "sources": [],
        "related": [],
        "created": today(),
        "updated": today(),
        "confidence": "low",
    }
    body = _template_body(fmtype, title)
    dest.write_text(serialize_frontmatter(meta) + "\n\n" + body, encoding="utf-8")
    print(f"created {dest.relative_to(root)}")


def _template_body(fmtype: str, title: str) -> str:
    if fmtype == "source-summary":
        return (f"# {title}\n\n"
                "One-line description of the source.\n\n"
                "## Summary\n\n## Key claims / results\n\n## Notable data points\n")
    if fmtype == "comparison":
        return (f"# {title}\n\n"
                "What is being compared and why.\n\n"
                "## Dimensions\n\n## Analysis\n\n## Takeaway\n")
    if fmtype == "entity":
        return (f"# {title}\n\n"
                "One-line description of the entity.\n\n"
                "## Background\n\n## Relevance\n")
    # concept (default)
    return (f"# {title}\n\n"
            "One-line definition.\n\n"
            "## Details\n\n## Why it matters\n")


def cmd_index(args):
    root = find_root(args.root)
    pages = [p for p in load_pages(root) if p.error is None]

    sections = [
        ("Concepts", "concept"),
        ("Entities", "entity"),
        ("Source Summaries", "source-summary"),
        ("Comparisons", "comparison"),
    ]
    lines = ["# Wiki Index", "",
             f"_Auto-generated by `wiki index` on {today()}. Do not edit by hand._", ""]
    listed = set()
    for heading, t in sections:
        group = sorted((p for p in pages if p.type == t), key=lambda p: p.wiki_rel)
        if not group:
            continue
        lines.append(f"## {heading}")
        for p in group:
            lines.append(f"- `{p.wiki_rel}` \u2013 {p.summary()}")
            listed.add(p.wiki_rel)
        lines.append("")

    other = sorted((p for p in pages if p.wiki_rel not in listed), key=lambda p: p.wiki_rel)
    if other:
        lines.append("## Other")
        for p in other:
            lines.append(f"- `{p.wiki_rel}` \u2013 {p.summary()} _(type: {p.type or '?'})_")
        lines.append("")

    (root / "wiki/index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"index rebuilt: {len(pages)} page(s) catalogued in wiki/index.md")


def cmd_log(args):
    root = find_root(args.root)
    log = root / "wiki/log.md"
    if not log.exists():
        log.write_text("# Activity Log\n", encoding="utf-8")
    entry = [f"\n{today()} {args.action} {args.title}"]
    if args.note:
        entry.append(f"Notes: {args.note}")
    with log.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")
    print(f"appended log entry: {today()} {args.action} {args.title}")


def cmd_search(args):
    root = find_root(args.root)
    needle = args.query.lower()
    hits = []
    for p in load_pages(root):
        hay = (p.path.read_text(encoding="utf-8", errors="ignore")).lower()
        if needle in hay or needle in p.wiki_rel.lower():
            title = p.meta.get("title", p.wiki_rel) if p.error is None else p.wiki_rel
            hits.append((p.wiki_rel, title))
    if not hits:
        print(f"no pages match {args.query!r}")
        return
    print(f"{len(hits)} match(es) for {args.query!r}:")
    for rel, title in hits:
        print(f"  {rel}  \u2014  {title}")


def cmd_lint(args):
    root = find_root(args.root)
    pages = load_pages(root)
    by_wikirel = {p.wiki_rel.rsplit(".md", 1)[0]: p for p in pages}

    errors = []   # (page, message)
    warnings = []

    # build inbound-link map for orphan detection.
    # Sources of inbound links = content pages PLUS the hand-written overview.md hub.
    # index.md is intentionally excluded (it links everything, which would hide all orphans).
    inbound = {key: 0 for key in by_wikirel}
    link_sources = list(pages)
    overview = root / "wiki" / "overview.md"
    if overview.exists():
        link_sources.append(Page(overview, root))
    for p in link_sources:
        if p.error:
            continue
        for tgt in p.link_targets():
            if tgt in inbound:
                inbound[tgt] += 1

    stale_cutoff = datetime.date.today() - datetime.timedelta(days=args.stale_days)

    for p in pages:
        if p.error:
            errors.append((p.rel, p.error))
            continue

        # required fields
        for field in REQUIRED_FIELDS:
            if not p.meta.get(field):
                errors.append((p.rel, f"missing required field: {field}"))

        # type
        if p.type and p.type not in PAGE_TYPES:
            errors.append((p.rel, f"invalid type {p.type!r} (allowed: {', '.join(PAGE_TYPES)})"))

        # confidence (optional but if present must be valid)
        conf = p.meta.get("confidence")
        if conf and conf not in CONFIDENCE:
            errors.append((p.rel, f"invalid confidence {conf!r} (allowed: {', '.join(CONFIDENCE)})"))

        # dates
        created = p.meta.get("created")
        updated = p.meta.get("updated")
        cdate = udate = None
        if created:
            cdate = _parse_date(created)
            if cdate is None:
                errors.append((p.rel, f"created is not a valid YYYY-MM-DD date: {created!r}"))
        if updated:
            udate = _parse_date(updated)
            if udate is None:
                errors.append((p.rel, f"updated is not a valid YYYY-MM-DD date: {updated!r}"))
        if cdate and udate and udate < cdate:
            errors.append((p.rel, f"updated ({updated}) is before created ({created})"))

        # broken related / wikilinks
        for tgt in p.link_targets():
            if tgt not in by_wikirel:
                errors.append((p.rel, f"broken wiki link/related -> {tgt} (no such page)"))

        # broken sources (must exist under raw/)
        for src in p.meta.get("sources", []) or []:
            sp = (root / src) if src.startswith("raw/") else (root / "raw" / src)
            if not sp.exists():
                errors.append((p.rel, f"source not found: {src}"))

        # --- warnings ---
        if inbound.get(p.wiki_rel.rsplit(".md", 1)[0], 0) == 0:
            warnings.append((p.rel, "orphan page (no inbound links from any other page)"))
        if udate and udate < stale_cutoff:
            warnings.append((p.rel, f"stale: updated {updated} (> {args.stale_days} days ago)"))
        if len(p.body.strip()) < 40:
            warnings.append((p.rel, "page body is nearly empty"))

    # --- report ---
    for path, msg in errors:
        print(f"[ERROR] {path}: {msg}")
    for path, msg in warnings:
        print(f"[WARN]  {path}: {msg}")

    n_pages = len(pages)
    if not errors and not warnings:
        print(f"[OK] {n_pages} page(s) checked, no issues.")
    else:
        print(f"\nchecked {n_pages} page(s): {len(errors)} error(s), {len(warnings)} warning(s).")

    return 1 if errors else 0


def _parse_date(s):
    """Return a date only for a strict YYYY-MM-DD real calendar date, else None."""
    s = str(s)
    if not DATE_RE.match(s):
        return None
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return datetime.date(y, m, d)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="wiki", description="LLM Wiki workflow tooling")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_root(sp):
        sp.add_argument("--root", help="wiki project root (default: auto-detect)")
        return sp

    sp = sub.add_parser("init", help="scaffold a new wiki project")
    sp.add_argument("path", help="directory to create")
    sp.set_defaults(func=cmd_init)

    sp = with_root(sub.add_parser("new", help="create a new wiki page"))
    sp.add_argument("kind", choices=list(NEW_KINDS.keys()))
    sp.add_argument("slug", help="page slug, e.g. attention-mechanism")
    sp.add_argument("--title", help="human-readable title")
    sp.set_defaults(func=cmd_new)

    sp = with_root(sub.add_parser("index", help="regenerate wiki/index.md"))
    sp.set_defaults(func=cmd_index)

    sp = with_root(sub.add_parser("lint", help="health-check the wiki"))
    sp.add_argument("--stale-days", type=int, default=90,
                    help="flag pages not updated in this many days (default 90)")
    sp.set_defaults(func=cmd_lint)

    sp = with_root(sub.add_parser("log", help="append an activity log entry"))
    sp.add_argument("action", help="ingest | query | lint | note")
    sp.add_argument("title", help="short title for the entry")
    sp.add_argument("--note", help="optional note line")
    sp.set_defaults(func=cmd_log)

    sp = with_root(sub.add_parser("search", help="find pages by keyword"))
    sp.add_argument("query")
    sp.set_defaults(func=cmd_search)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    sys.exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
