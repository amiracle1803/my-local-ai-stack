import { useEffect, useState } from "react";
import { api, type ObsidianNote, type ObsidianSearchResult } from "../api/client";

export default function Knowledge() {
  const [tab, setTab] = useState<"browse" | "search">("browse");
  const [notes, setNotes] = useState<ObsidianNote[] | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ObsidianSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");

  useEffect(() => {
    if (tab === "browse" && !notes) {
      api.obsidian.notes(100).then(setNotes).catch(() => setNotes([]));
    }
  }, [tab, notes]);

  async function doSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    try {
      const res = await api.obsidian.search(query, 8);
      setResults(res.results);
    } finally {
      setSearching(false);
    }
  }

  async function reindex() {
    setReindexing(true);
    setReindexMsg("");
    try {
      const res = await api.obsidian.reindex();
      setReindexMsg(`Indexed ${res.indexed} changed note(s).`);
      setNotes(null);
    } finally {
      setReindexing(false);
    }
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Knowledge</span>
        <span className="topbar-sub">Semantic search over your Obsidian vault</span>
        <div className="topbar-right">
          <button className="btn btn-ghost btn-sm" onClick={reindex} disabled={reindexing}>
            {reindexing ? "Indexing…" : "Reindex vault"}
          </button>
        </div>
      </div>
      <div className="page">
        {reindexMsg && <div className="alert alert-ok">{reindexMsg}</div>}

        <div className="tabs">
          <button className={`tab${tab === "browse" ? " on" : ""}`} onClick={() => setTab("browse")}>Browse</button>
          <button className={`tab${tab === "search" ? " on" : ""}`} onClick={() => setTab("search")}>Search</button>
        </div>

        {tab === "search" && (
          <>
            <form onSubmit={doSearch} className="card" style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", gap: 10 }}>
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the vault…" />
                <button type="submit" className="btn btn-primary" disabled={searching || !query.trim()}>
                  {searching ? "…" : "Search"}
                </button>
              </div>
            </form>
            {results && (
              <div className="job-list">
                {results.length === 0 && <div className="empty-box"><h3>No results</h3></div>}
                {results.map((r) => (
                  <div key={r.id} className="job-row" style={{ cursor: "default", flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
                    <div style={{ display: "flex", width: "100%", gap: 10, alignItems: "center" }}>
                      <span className="job-goal">{r.title}</span>
                      <span className="badge b-indigo">{r.score.toFixed(2)}</span>
                    </div>
                    {r.snippet && <div style={{ fontSize: 12, color: "var(--text3)" }}>{r.snippet.slice(0, 160)}</div>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === "browse" && (
          <div className="job-list">
            {!notes && <div className="loading-row"><div className="spinner" />Loading…</div>}
            {notes && notes.length === 0 && <div className="empty-box"><h3>No notes indexed yet</h3><p>Click "Reindex vault" above.</p></div>}
            {notes?.map((n) => (
              <div key={n.id} className="job-row" style={{ cursor: "default" }}>
                <span className="job-goal">{n.title}</span>
                {n.tags.length > 0 && <span className="badge b-gray">{n.tags.join(", ")}</span>}
                <span className="job-meta">{new Date(n.indexed_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
