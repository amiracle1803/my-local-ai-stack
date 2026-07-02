import { useEffect, useState, useRef } from "react";
import { wsClient } from "../api/ws";

export interface AgentSlot {
  id:      string;
  busy:    boolean;
  task:    string | null;
  msgType: string | null;
  jobId:   string | null;
  since:   Date | null;
}

const BUSY_TTL_MS = 8_000;

export function useAgentActivity(allAgentIds: string[] = []) {
  const [slots, setSlots] = useState<Record<string, AgentSlot>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Seed slots when agent list loads
  useEffect(() => {
    if (!allAgentIds.length) return;
    setSlots(prev => {
      const next = { ...prev };
      for (const id of allAgentIds) {
        if (!next[id]) next[id] = { id, busy: false, task: null, msgType: null, jobId: null, since: null };
      }
      return next;
    });
  }, [allAgentIds.join(",")]); // eslint-disable-line

  function markBusy(agentId: string, task: string | null, msgType: string, jobId: string | null) {
    const now = new Date();
    setSlots(prev => ({
      ...prev,
      [agentId]: {
        id:      agentId,
        busy:    true,
        task:    task ?? prev[agentId]?.task ?? null,
        msgType,
        jobId,
        since:   prev[agentId]?.busy ? prev[agentId].since : now,
      },
    }));
    clearTimeout(timers.current[agentId]);
    timers.current[agentId] = setTimeout(() => {
      setSlots(prev => ({
        ...prev,
        [agentId]: { ...(prev[agentId] ?? { id: agentId, jobId: null, since: null }), busy: false, task: null, msgType: null },
      }));
    }, BUSY_TTL_MS);
  }

  function clearJobAgents(jid: string) {
    setSlots(prev => {
      const next = { ...prev };
      for (const [id, slot] of Object.entries(next)) {
        if (slot.jobId === jid) next[id] = { ...slot, busy: false, task: null, since: null };
      }
      return next;
    });
  }

  // Cancel all pending busy-TTL timers when the hook unmounts.
  useEffect(() => () => { Object.values(timers.current).forEach(clearTimeout); }, []);

  useEffect(() => {
    return wsClient.subscribe(raw => {
      const ev = raw.event as string | undefined;
      if (!ev) return;

      if (ev === "agent_message") {
        const from   = raw.from   as string;
        const to     = raw.to     as string;
        const type   = raw.type   as string;
        const task   = (raw.task  as string | null) ?? null;
        const jobId  = (raw.job_id as string | null) ?? null;

        if (from && from !== "user") markBusy(from, null,  type, jobId);
        if (to   && to   !== "user") markBusy(to,   task,  type, jobId);
        return;
      }

      if (ev === "job_update") {
        const status = raw.status as string;
        const jid    = raw.job_id as string | null ?? null;
        if (jid && (status === "done" || status === "failed" || status === "stopped")) {
          clearJobAgents(jid);
        }
      }
    });
  }, []); // eslint-disable-line

  return slots;
}

export type ActivityMap = Record<string, AgentSlot>;
