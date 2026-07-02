import { useEffect, useState, useCallback } from "react";
import { api, type ObsidianNote, type ObsidianSearchResult } from "../api/client";

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function Knowledge() {
  const [notes,    setNotes]    = useState<ObsidianNote[] | null>(null);
  const [results,  setResults]  = useState<ObsidianSearchResult[] | null>(null);
  const [query,    setQuery]    = useState("");
  const [tab,      setTab]      = useState<"browse" | "search">("browse");
  const [indexing, setIndexing] = useState(false);
  const [err,      setErr]      = useState<string | null>(null);
  const [indexMsg, setIndexMsg] = useState<string | null>(null);

  const loadNotes = useCallback(() => {
    api.obsidian.notes(200).then(setNotes).catch((e) => setErr(e.message));
  }, []);

  useEffect(() => { loadNotes(); }, [loadNotes]);

  async function search() {
    if (!query.trim()) return;
    setErr(null);
    try {
      const r = await api.obsidian.search(query.trim(), 10);
      setResults(r.results);
      setTab("search");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function reindex() {
    setIndexing(true); setIndexMsg(null);
    try {
      const r = await api.obsidian.reindex();
      setIndexMsg(`Indexed ${r.indexed} notes.`);
      loadNotes();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setIndexing(false);
    }
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Knowledge</span>
        <span className="topbar-sub">
          {notes ? `${notes.length} notes in Obsidian vault` : "Obsidian notes"}
        </span>
        <div className="topbar-right">
          <button className="btn btn-ghost btn-sm" onClick={reindex} disabled={indexing}>
            {indexing ? <><div className="spinner spinner-sm" /> Indexing…</> : "↻ Re-index"}
          </button>
        </div>
      </div>
      <div className="page">
        {err      && <div className="alert alert-err">{err}</div>}
        {indexMsg && <div className="alert alert-ok" style={{ marginBottom: 16 }}>{indexMsg}</div>}

        {/* Search bar */}
        <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
          <input
            type="search"
            placeholder="Semantic search your notes…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" onClick={search} disabled={!query.trim()}>
            Search
          </button>
          {tab === "search" && (
            <button className="btn btn-ghost" onClick={() => { setTab("browse"); setResults(null); setQuery(""); }}>
              Clear
            </button>
          )}
        </div>

        <div className="tabs">
          <button className={`tab${tab === "browse" ? " on" : ""}`} onClick={() => setTab("browse")}>
            Browse ({notes?.length ?? "…"})
          </button>
          {results !== null && (
            <button className={`tab${tab === "search" ? " on" : ""}`} onClick={() => setTab("search")}>
              Results ({results.length})
            </button>
          )}
        </div>

        {/* Browse */}
        {tab === "browse" && (
          <>
            {!notes && <div className="loading-row"><div className="spinner" /> Loading notes…</div>}
            {notes?.length === 0 && (
              <div className="empty-box">
                <h3>No notes indexed</h3>
                <p>Click "Re-index" to scan the Obsidian vault.</p>
              </div>
            )}
            {notes && notes.length > 0 && (
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                {notes.map((n) => (
                  <div
                    key={n.id}
                    style={{
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "11px 18px",
                      borderBottom: "1px solid var(--border)",
                    }}
                  >
                    <span style={{ fontSize: 16 }}>📄</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {n.title || n.path}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 2 }}>
                        {n.path}
                      </div>
                    </div>
                    {n.tags.length > 0 && (
                      <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                        {n.tags.slice(0, 2).map((t) => (
                          <span key={t} className="chip">{t}</span>
                        ))}
                      </div>
                    )}
                    <span style={{ fontSize: 11, color: "var(--text3)", flexShrink: 0 }}>
                      {fmtDate(n.indexed_at)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Search results */}
        {tab === "search" && results !== null && (
          <>
            {results.length === 0 && (
              <div className="empty-box">
                <h3>No results found</h3>
                <p>Try a different query.</p>
              </div>
            )}
            {results.map((r, i) => (
              <div key={r.id} className="card" style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "flex-start", marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 2 }}>
                    #{i + 1}
                  </span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 3 }}>
                      {r.title || r.path}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)" }}>
                      {r.path}
                    </div>
                  </div>
                  <span className="badge b-indigo">
                    {Math.round(r.score * 100)}% match
                  </span>
                </div>
                {r.snippet && (
                  <div style={{
                    fontSize: 12, color: "var(--text2)", lineHeight: 1.65,
                    borderLeft: "2px solid var(--border2)", paddingLeft: 12,
                  }}>
                    {r.snippet}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}
