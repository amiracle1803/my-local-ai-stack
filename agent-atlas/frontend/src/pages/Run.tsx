import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Job, type RiskLevel, POLICY_LABELS, RISK_POLICY } from "../api/client";
import ResultView, { extractText } from "../components/ResultView";
import LiveFeed from "../components/LiveFeed";

const EXAMPLES = [
  "Summarize the latest AI research papers in my knowledge base",
  "Write a Python script that reads CSV files and outputs statistics",
  "Search for notes about transformers and create a synthesis",
  "Review the agent architecture and suggest three improvements",
];

type Phase = "form" | "running";

interface Turn {
  goal:  string;
  jobId: string;
  result: unknown | null;
  status: string;
}

function statusBadge(s: string) {
  const m: Record<string, string> = { running:"b-blue", done:"b-green", failed:"b-red", queued:"b-yellow", paused:"b-yellow", stopped:"b-gray" };
  return m[s] ?? "b-gray";
}

export default function Run() {
  const navigate = useNavigate();

  // Form state
  const [phase,   setPhase]   = useState<Phase>("form");
  const [goal,    setGoal]    = useState("");
  const [risk,    setRisk]    = useState<RiskLevel>("low");
  const [busy,    setBusy]    = useState(false);
  const [err,     setErr]     = useState<string | null>(null);

  // Conversation state
  const [history, setHistory] = useState<Turn[]>([]);   // completed turns
  const [job,     setJob]     = useState<Job | null>(null);  // current job

  // Follow-up state
  const [followUp,  setFollowUp]  = useState("");
  const [fuBusy,    setFuBusy]    = useState(false);
  const [fuErr,     setFuErr]     = useState<string | null>(null);
  const followUpRef = useRef<HTMLTextAreaElement>(null);

  // Poll current job; stop after 3 consecutive errors (e.g. job deleted / 404)
  const pollJob = useCallback((id: string) => {
    let errors = 0;
    const iv = setInterval(async () => {
      try {
        const j = await api.jobs.get(id);
        errors = 0;
        setJob(j);
        if (j.status === "done" || j.status === "failed" || j.status === "stopped") clearInterval(iv);
      } catch {
        errors++;
        if (errors >= 3) clearInterval(iv);
      }
    }, 2000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (!job?.id || phase !== "running") return;
    if (job.status === "done" || job.status === "failed" || job.status === "stopped") return;
    return pollJob(job.id);
  }, [job?.id, phase, pollJob]);

  // When job finishes, focus the follow-up box
  useEffect(() => {
    if (job?.status === "done") {
      setTimeout(() => followUpRef.current?.focus(), 300);
    }
  }, [job?.status]);

  async function submit(
    goalText = goal,
    contextPayload: Record<string, unknown> = {},
    setErrorFn: (msg: string | null) => void = setErr,
  ) {
    if (!goalText.trim()) return;
    setBusy(true); setErrorFn(null);
    try {
      const res = await api.run(goalText.trim(), {
        risk_level:    risk,
        review_policy: RISK_POLICY[risk],
        run_mode:      "background",
        context:       contextPayload,
      });
      if (res.job_id) {
        const j = await api.jobs.get(res.job_id);
        setJob(j);
        setPhase("running");
        setGoal("");
        setFollowUp("");
        setFuErr(null);
      } else {
        setErrorFn("No job ID returned. Check backend.");
      }
    } catch (e: unknown) {
      setErrorFn(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submitFollowUp() {
    if (!followUp.trim() || !job) return;
    setFuBusy(true); setFuErr(null);

    // Archive current turn into history
    const currentTurn: Turn = {
      goal:   job.title ?? "",
      jobId:  job.id,
      result: job.result,
      status: job.status,
    };
    setHistory(h => [...h, currentTurn]);

    // Build context from the entire conversation
    const prevResult = extractText(job.result);
    const context: Record<string, unknown> = {
      is_followup:       true,
      conversation_turn: history.length + 1,
      previous_goal:     currentTurn.goal,
      previous_result:   prevResult.slice(0, 1200),
      conversation_history: [...history, currentTurn].map(t => ({
        goal:   t.goal,
        result: extractText(t.result).slice(0, 400),
      })),
    };

    const fuGoal = followUp.trim();
    setFollowUp("");
    setFuBusy(false);
    // Pass setFuErr so errors appear in the follow-up box, not in the top-level form err state.
    await submit(fuGoal, context, setFuErr);
  }

  function reset() {
    setPhase("form");
    setJob(null);
    setErr(null);
    setGoal("");
    setHistory([]);
    setFollowUp("");
    setFuErr(null);
  }

  // ── Live execution view ────────────────────────────────────────────────────
  if (phase === "running" && job) {
    const isDone     = job.status === "done";
    const isFailed   = job.status === "failed";
    const isStopped  = job.status === "stopped";
    const isFinished = isDone || isFailed || isStopped;
    const isActive   = !isFinished;
    const currentGoal = job.title ?? history[history.length - 1]?.goal ?? "";

    return (
      <>
        <div className="topbar">
          <span className="topbar-title" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {currentGoal || "Running task…"}
          </span>
          <span className={`badge ${statusBadge(job.status)}`}>{job.status}</span>
          {history.length > 0 && (
            <span style={{ fontSize: 11, color: "var(--text3)" }}>
              Turn {history.length + 1}
            </span>
          )}
          <div className="topbar-right">
            {isActive && (
              <button className="btn btn-danger btn-sm"
                onClick={async () => { await api.jobs.stop(job.id); const j = await api.jobs.get(job.id); setJob(j); }}>
                ⏹ Stop
              </button>
            )}
            {(isStopped || isFailed) && (
              <button className="btn btn-success btn-sm"
                onClick={async () => { const r = await api.jobs.retry(job.id); const j = await api.jobs.get(r.id); setJob(j); }}>
                ↺ Retry
              </button>
            )}
            {isFinished && (
              <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/jobs/${job.id}`)}>
                View job →
              </button>
            )}
            <button className="btn btn-ghost btn-sm" onClick={reset}>
              New task
            </button>
          </div>
        </div>

        <div className="page" style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* ── Conversation history ── */}
          {history.map((turn, i) => (
            <div key={turn.jobId} style={{
              background: "var(--s1)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r2)",
              overflow: "hidden",
            }}>
              {/* User message */}
              <div style={{
                display: "flex", alignItems: "flex-start", gap: 10,
                padding: "12px 16px",
                borderBottom: "1px solid var(--border)",
                background: "var(--s2)",
              }}>
                <div style={{
                  width: 24, height: 24, borderRadius: 6, flexShrink: 0,
                  background: "rgba(99,102,241,.2)", border: "1px solid rgba(99,102,241,.3)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 800, color: "var(--accent2)",
                }}>
                  {i + 1}
                </div>
                <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500, paddingTop: 3 }}>
                  {turn.goal}
                </div>
              </div>
              {/* Agent result */}
              {!!turn.result && (
                <div style={{ padding: "14px 16px" }}>
                  <ResultView result={turn.result} />
                </div>
              )}
            </div>
          ))}

          {/* ── Current job ── */}
          <div>
            {/* Current user message */}
            <div style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "12px 16px",
              background: "var(--s2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r2) var(--r2) 0 0",
              borderBottom: "none",
            }}>
              <div style={{
                width: 24, height: 24, borderRadius: 6, flexShrink: 0,
                background: "rgba(99,102,241,.2)", border: "1px solid rgba(99,102,241,.3)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 10, fontWeight: 800, color: "var(--accent2)",
              }}>
                {history.length + 1}
              </div>
              <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 500, paddingTop: 3 }}>
                {currentGoal}
              </div>
            </div>

            {/* Progress bar */}
            <div style={{ background: "var(--s1)", border: "1px solid var(--border)", borderTop: "none", padding: "10px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text3)", marginBottom: 4 }}>
                <span style={{ fontFamily: "var(--mono)" }}>{job.id.slice(0, 16)}…</span>
                <span>{isFinished ? "100%" : job.progress > 0 ? `${Math.round(job.progress * 100)}%` : "working…"}</span>
              </div>
              <div className="progress-bar" style={{ height: 4 }}>
                <div className="progress-fill" style={{
                  width: isFinished ? "100%" : job.progress > 0 ? `${Math.round(job.progress * 100)}%` : "0%",
                  background: isDone ? "var(--green)" : isFailed ? "var(--red)" : "var(--accent)",
                }} />
              </div>
            </div>

            {/* Live feed */}
            <div style={{ border: "1px solid var(--border)", borderTop: "none", padding: "12px 14px", background: "var(--bg)" }}>
              <LiveFeed jobId={job.id} status={job.status} />
            </div>

            {/* Result */}
            {isDone && !!job.result && (
              <div style={{
                border: "1px solid var(--border)", borderTop: "none",
                borderRadius: "0 0 var(--r2) var(--r2)",
                background: "var(--s1)", padding: "16px 18px",
              }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 10 }}>
                  Result
                </div>
                <ResultView result={job.result} />
              </div>
            )}

            {/* Error / stopped state */}
            {isFailed && (
              <div style={{ border: "1px solid var(--border)", borderTop: "none", borderRadius: "0 0 var(--r2) var(--r2)" }}>
                <div className="alert alert-err" style={{ margin: 12, borderRadius: "var(--r)" }}>
                  <span>✕</span><span>{job.error ?? "Task failed."}</span>
                </div>
              </div>
            )}
            {isStopped && (
              <div style={{ border: "1px solid var(--border)", borderTop: "none", borderRadius: "0 0 var(--r2) var(--r2)" }}>
                <div className="alert alert-warn" style={{ margin: 12, borderRadius: "var(--r)" }}>
                  <span>⏹</span><span>Task stopped. Use Retry or send a follow-up.</span>
                </div>
              </div>
            )}
          </div>

          {/* ── Follow-up box ── appears when job is done or stopped ── */}
          {isFinished && (
            <div style={{
              background: "var(--s1)",
              border: "2px solid var(--accent)",
              borderRadius: "var(--r2)",
              padding: "14px 16px",
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--accent2)", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                <span>↩</span> Follow up
                {history.length > 0 && (
                  <span style={{ fontWeight: 400, color: "var(--text3)", marginLeft: 4 }}>
                    · agents will see the previous result as context
                  </span>
                )}
              </div>

              {fuErr && <div className="alert alert-err" style={{ marginBottom: 10 }}>{fuErr}</div>}

              <textarea
                ref={followUpRef}
                rows={3}
                value={followUp}
                onChange={e => setFollowUp(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitFollowUp(); }}
                placeholder="Ask a follow-up, request changes, or build on this result…"
                disabled={fuBusy || busy}
                style={{ marginBottom: 10 }}
              />

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  className="btn btn-primary"
                  onClick={submitFollowUp}
                  disabled={fuBusy || busy || !followUp.trim()}
                >
                  {fuBusy ? <><div className="spinner spinner-sm" /> Sending…</> : "↩ Send follow-up"}
                </button>
                <span style={{ fontSize: 11, color: "var(--text3)" }}>Ctrl+Enter</span>
                <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={reset}>
                  Start fresh
                </button>
              </div>
            </div>
          )}

        </div>
      </>
    );
  }

  // ── Task form ──────────────────────────────────────────────────────────────
  return (
    <>
      <div className="topbar">
        <span className="topbar-title">Run Task</span>
        <span className="topbar-sub">Submit a goal — watch agents execute it live</span>
      </div>
      <div className="page">
        <div style={{ maxWidth: 640 }}>
          {err && <div className="alert alert-err">{err}</div>}

          <div className="field">
            <label>What do you want the agents to do?</label>
            <textarea
              rows={6}
              value={goal}
              onChange={e => setGoal(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); }}
              placeholder="Describe your goal in plain language. The orchestrator will break it down and delegate to the right agents…"
              disabled={busy}
              autoFocus
            />
            <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 5 }}>Ctrl+Enter to submit</div>
          </div>

          <div className="field">
            <label>Risk level</label>
            <div style={{ display: "flex", gap: 8 }}>
              {(["low","medium","high","critical"] as RiskLevel[]).map(r => (
                <button key={r} className={`btn btn-sm ${risk === r ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setRisk(r)} disabled={busy} style={{ textTransform: "capitalize" }}>
                  {r}
                </button>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 8 }}>{POLICY_LABELS[RISK_POLICY[risk]]}</div>
          </div>

          <button className="btn btn-primary" onClick={() => submit()} disabled={busy || !goal.trim()}
            style={{ width: "100%", justifyContent: "center", padding: "13px", fontSize: 14 }}>
            {busy ? <><div className="spinner spinner-sm" /> Submitting…</> : "▷ Run task"}
          </button>

          <hr className="divider" />
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text3)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 10 }}>
            Try an example
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {EXAMPLES.map(ex => (
              <button key={ex} className="btn btn-ghost" style={{ justifyContent: "flex-start", textAlign: "left" }}
                onClick={() => setGoal(ex)} disabled={busy}>
                <span style={{ color: "var(--accent2)", marginRight: 6 }}>→</span>{ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
