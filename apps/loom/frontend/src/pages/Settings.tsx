import { useEffect, useState } from "react";
import { api, type HealthInfo, type ModelInfo } from "../api/client";

const LANGFUSE_URL = "http://localhost:3030";

export default function Settings() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [mcpCopied, setMcpCopied] = useState(false);

  const mcpUrl = `${window.location.origin}/mcp/sse`;

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.llm.models().then(setModels).catch(() => setModels([]));
  }, []);

  function copyMcpUrl() {
    navigator.clipboard?.writeText(mcpUrl).then(() => {
      setMcpCopied(true);
      setTimeout(() => setMcpCopied(false), 2000);
    });
  }

  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Settings</span>
        <span className="topbar-sub">System info</span>
      </div>
      <div className="page">
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="section-hd"><h2>Service</h2></div>
          {health ? (
            <div className="g3">
              <div className="stat-box"><div className="stat-n">{health.status}</div><div className="stat-l">Status</div></div>
              <div className="stat-box"><div className="stat-n">{health.agents_loaded}</div><div className="stat-l">Agents</div></div>
              <div className="stat-box"><div className="stat-n">{health.models_loaded}</div><div className="stat-l">Models configured</div></div>
            </div>
          ) : (
            <div className="loading-row"><div className="spinner" />Checking…</div>
          )}
        </div>

        <div className="card" style={{ marginBottom: 16 }}>
          <div className="section-hd"><h2>Model availability</h2></div>
          {!models && <div className="loading-row"><div className="spinner" />Probing…</div>}
          {models && (
            <table className="tbl">
              <thead><tr><th>Name</th><th>Provider</th><th>Capabilities</th><th>Available</th></tr></thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.name}>
                    <td>{m.name}</td>
                    <td>{m.provider}</td>
                    <td>{m.capabilities.join(", ")}</td>
                    <td>
                      <span className={`badge ${m.available ? "b-green" : "b-gray"}`}>
                        {m.available ? "available" : "unavailable"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card" style={{ marginBottom: 16 }}>
          <div className="section-hd"><h2>Observability</h2></div>
          <p style={{ fontSize: 13, color: "var(--text2)", marginBottom: 10 }}>
            Every agent call is traced to a self-hosted Langfuse instance -- duration, success/failure,
            input/output previews. Silently skipped if Langfuse isn't running, so it never blocks a real request.
          </p>
          <a className="btn btn-ghost btn-sm" href={LANGFUSE_URL} target="_blank" rel="noopener">
            Open Langfuse traces →
          </a>
        </div>

        <div className="card">
          <div className="section-hd"><h2>Connect an external tool (MCP)</h2></div>
          <p style={{ fontSize: 13, color: "var(--text2)", marginBottom: 10 }}>
            Loom is an MCP server -- point Claude Desktop, Claude Code, Cursor, or any other MCP client
            at this URL to give it Loom's tools (ask a goal, search the vault, manage background jobs).
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <code className="codeblock" style={{ flex: 1, padding: "8px 12px", maxHeight: "none" }}>{mcpUrl}</code>
            <button className="btn btn-ghost btn-sm" onClick={copyMcpUrl}>{mcpCopied ? "Copied ✓" : "Copy"}</button>
          </div>
        </div>
      </div>
    </>
  );
}
