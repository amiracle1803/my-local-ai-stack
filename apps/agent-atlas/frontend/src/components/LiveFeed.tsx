import { useEffect, useRef, useState } from "react";
import { wsClient } from "../api/ws";

interface FeedItem {
  id:      string;
  from:    string;
  to:      string;
  msgType: string;
  task:    string | null;
  ts:      string;
  isStatus?: boolean;
}

const TYPE_LABEL: Record<string, string> = {
  user_goal:        "submitted goal to orchestrator",
  plan_request:     "requested a plan from planner",
  subtask:          "delegated subtask",
  research_request: "researching",
  code_request:     "writing code",
  evaluate_request: "evaluating output",
  search:           "searching knowledge base",
  retrieve_request: "retrieving documents",
  create_doc:       "creating document",
  schedule:         "scheduling automation",
  completed:        "task completed",
  failed:           "task failed",
  stopped:          "task stopped",
};

function agentColor(id: string) {
  if (id === "orchestrator")                                                   return "#a855f7";
  if (id === "planner")                                                        return "#6366f1";
  if (id === "evaluator" || id === "guardian_agent")                           return "#f59e0b";
  if (["knowledge_hub","retrieval_agent","obsidian_brain","memory_agent"].includes(id)) return "#3b82f6";
  if (id === "code_agent")                                                     return "#22c55e";
  if (id === "creative_studio_agent")                                          return "#ec4899";
  if (id === "background_runtime" || id === "system")                         return "#64748b";
  return "#6366f1";
}

function initials(id: string) {
  return id.replace(/_agent$/, "").split("_").map(w => w[0]?.toUpperCase() ?? "").join("").slice(0, 2) || "??";
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function LiveFeed({ jobId, status }: { jobId: string | null; status?: string }) {
  const [items,  setItems]  = useState<FeedItem[]>([]);
  const [active, setActive] = useState<Set<string>>(new Set());
  const [scroll, setScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const timers    = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => { setItems([]); setActive(new Set()); }, [jobId]);

  // Cancel all active-agent timers when the component unmounts.
  useEffect(() => () => { Object.values(timers.current).forEach(clearTimeout); }, []);

  useEffect(() => {
    return wsClient.subscribe(raw => {
      const ev = raw.event as string | undefined;
      if (!ev) return;

      if (ev === "agent_message") {
        const from    = raw.from as string;
        const to      = raw.to as string;
        const msgType = raw.type as string;
        const jid     = raw.job_id as string | null ?? null;
        const task    = raw.task as string | null ?? null;

        if (jobId && jid && jid !== jobId) return;
        if (from === "system" && msgType === "pong") return;

        const item: FeedItem = { id: `${Date.now()}-${Math.random()}`, from, to, msgType, task, ts: new Date().toISOString() };
        setItems(p => [...p, item]);

        for (const a of [from, to]) {
          if (!a || a === "user") continue;
          setActive(s => new Set([...s, a]));
          clearTimeout(timers.current[a]);
          timers.current[a] = setTimeout(() => setActive(s => { const n = new Set(s); n.delete(a); return n; }), 3500);
        }
      }

      if (ev === "job_update") {
        const jid    = raw.job_id as string | null ?? null;
        const status = raw.status as string;
        if (jobId && jid && jid !== jobId) return;
        if (status === "done" || status === "failed" || status === "stopped") {
          setItems(p => [...p, {
            id: `sys-${Date.now()}`, from: "system", to: "user",
            msgType: status, task: null, ts: new Date().toISOString(), isStatus: true,
          }]);
          setActive(new Set());
        }
      }
    });
  }, [jobId]);

  useEffect(() => {
    if (scroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, scroll]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) setScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };

  const seenAgents = [...new Map(items.map(i => [i.from, i])).values()];
  const isRunning  = status === "running" || status === "queued";

  return (
    <div style={{ display: "flex", gap: 14 }}>

      {/* ── Message stream ── */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          ref={scrollRef}
          onScroll={onScroll}
          style={{ background: "var(--s2)", border: "1px solid var(--border)", borderRadius: "var(--r2)", minHeight: 240, maxHeight: 480, overflowY: "auto", padding: "6px 0" }}
        >
          {items.length === 0 && (
            <div style={{ textAlign: "center", padding: "44px 20px", color: "var(--text3)", fontSize: 13 }}>
              {isRunning ? <><div className="spinner" style={{ margin: "0 auto 10px" }} /><div>Waiting for agents…</div></> : "No activity recorded."}
            </div>
          )}

          {items.map(item => {
            const color = agentColor(item.from);
            return (
              <div key={item.id} style={{
                display: "flex", gap: 9, padding: "7px 13px",
                borderBottom: "1px solid var(--border)",
                background: item.isStatus ? `${color}0a` : "transparent",
              }}>
                {/* Avatar */}
                <div style={{
                  width: 24, height: 24, borderRadius: 5, flexShrink: 0, marginTop: 2,
                  background: `${color}1a`, border: `1px solid ${color}33`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 8, fontWeight: 800, color, fontFamily: "var(--mono)",
                }}>
                  {initials(item.from)}
                </div>

                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                    <span style={{ fontWeight: 700, color }}>{item.from}</span>
                    <span style={{ color: "var(--text3)", margin: "0 5px" }}>→</span>
                    <span style={{ color: agentColor(item.to), fontWeight: 600 }}>{item.to}</span>
                    <span style={{ color: "var(--text3)", marginLeft: 6 }}>
                      {TYPE_LABEL[item.msgType] ?? item.msgType}
                    </span>
                  </div>
                  {item.task && (
                    <div style={{ fontSize: 11, color: "var(--text2)", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      "{item.task}"
                    </div>
                  )}
                </div>

                <span style={{ fontSize: 10, color: "var(--text3)", fontFamily: "var(--mono)", flexShrink: 0, marginTop: 3 }}>
                  {fmtTime(item.ts)}
                </span>
              </div>
            );
          })}

          {isRunning && items.length > 0 && (
            <div style={{ display: "flex", gap: 8, padding: "8px 13px", alignItems: "center" }}>
              <div className="spinner spinner-sm" />
              <span style={{ fontSize: 11, color: "var(--text3)" }}>Agents working…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {!scroll && (
          <button className="btn btn-ghost btn-xs" style={{ marginTop: 5, float: "right" }}
            onClick={() => { setScroll(true); bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }}>
            ↓ Latest
          </button>
        )}
      </div>

      {/* ── Active agents panel ── */}
      <div style={{ width: 152, flexShrink: 0 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>
          Active agents
        </div>
        {seenAgents.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text3)" }}>{isRunning ? "Starting…" : "—"}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {seenAgents.map(item => {
              const on    = active.has(item.from);
              const color = agentColor(item.from);
              return (
                <div key={item.from} style={{
                  display: "flex", gap: 6, alignItems: "center",
                  padding: "5px 8px", borderRadius: "var(--r)",
                  background: on ? `${color}12` : "var(--s1)",
                  border: `1px solid ${on ? color + "44" : "var(--border)"}`,
                  transition: "all .2s",
                }}>
                  <div style={{
                    width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
                    background: on ? color : "var(--text3)",
                    boxShadow: on ? `0 0 5px ${color}` : "none",
                    animation: on ? "pulse-dot 1s infinite" : "none",
                  }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: on ? color : "var(--text2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.from.replace(/_agent$/, "")}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
