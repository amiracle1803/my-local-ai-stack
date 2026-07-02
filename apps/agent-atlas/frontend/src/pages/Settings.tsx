import { useEffect, useState } from "react";
import { api, type HealthInfo, type ModelInfo } from "../api/client";

export default function Settings() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.llm.models().then(setModels).catch(() => setModels([]));
  }, []);

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

        <div className="card">
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
      </div>
    </>
  );
}
