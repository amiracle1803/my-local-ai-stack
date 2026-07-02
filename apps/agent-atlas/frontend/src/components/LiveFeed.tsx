import { useEffect, useRef, useState } from "react";
import { wsClient, type WsEvent } from "../api/ws";

interface FeedStep {
  agent: string;
  action: string;
  at: number;
}

const AGENT_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator",
  planner: "Planner",
  evaluator: "Evaluator",
  knowledge_hub: "Knowledge Hub",
  obsidian_brain: "Obsidian Brain",
  memory_agent: "Memory Agent",
  code_agent: "Code Agent",
  automation_agent: "Automation Agent",
};

const ACTION_LABEL: Record<string, string> = {
  run: "is working on your task",
  plan: "is sketching an approach",
  evaluate: "is reviewing the draft answer",
  search: "is searching your vault",
  reindex: "is reindexing the vault",
  draft_workflow: "is drafting an n8n workflow",
};

function friendlyAgent(id: string): string {
  return AGENT_LABEL[id] ?? id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function friendlyAction(type: string): string {
  return ACTION_LABEL[type] ?? `is handling "${type}"`;
}

/** Live, job-scoped timeline of which agent is doing what, right now. */
export default function LiveFeed({ jobId, active }: { jobId: string | null; active: boolean }) {
  const [steps, setSteps] = useState<FeedStep[]>([]);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    setSteps([]);
    startRef.current = Date.now();
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;
    return wsClient.subscribe((e: WsEvent) => {
      if (e.event !== "agent_message") return;
      if (e.job_id !== jobId) return;
      const agent = e.to_agent as string;
      const type = e.type as string;
      setSteps((prev) => [...prev, { agent, action: type, at: Date.now() }]);
    });
  }, [jobId]);

  if (!jobId) {
    return (
      <div className="empty-box">
        <h3>Nothing running yet</h3>
        <p>Submit a task above and you'll see each agent's work appear here in real time.</p>
      </div>
    );
  }

  return (
    <div>
      {steps.length === 0 && (
        <div className="loading-row"><div className="spinner" />Connecting to Loom…</div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {steps.map((s, i) => {
          const isLast = i === steps.length - 1;
          const stillWorking = isLast && active;
          return (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 3 }}>
                <span className={`dot ${stillWorking ? "spin" : "on"}`} />
                {i < steps.length - 1 && <div style={{ width: 1, flex: 1, minHeight: 16, background: "var(--border)", marginTop: 4 }} />}
              </div>
              <div style={{ flex: 1, paddingBottom: 4 }}>
                <div style={{ fontSize: 13 }}>
                  <strong>{friendlyAgent(s.agent)}</strong>{" "}
                  <span style={{ color: "var(--text2)" }}>{friendlyAction(s.action)}</span>
                  {stillWorking && <span style={{ color: "var(--yellow)" }}> …</span>}
                </div>
                <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)" }}>
                  {new Date(s.at).toLocaleTimeString()}
                </div>
              </div>
            </div>
          );
        })}
        {!active && steps.length > 0 && (
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
            <span className="dot on" style={{ background: "var(--green)" }} />
            <div style={{ fontSize: 13, color: "var(--green)" }}>Done</div>
          </div>
        )}
      </div>
    </div>
  );
}
