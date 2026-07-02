import { useEffect, useState } from "react";
import { wsClient, type WsEvent } from "../api/ws";

export interface AgentActivitySlot {
  busy: boolean;
  task?: string;
  msgType?: string;
  jobId?: string;
  since?: number;
}

type ActivityMap = Record<string, AgentActivitySlot>;

const BUSY_TTL_MS = 8000;

/**
 * Single shared store, subscribed to the WS bus exactly once at module
 * load. Every component calling useAgentActivity() reads the same state
 * via subscription rather than each opening its own WS listener and
 * deriving busy-state independently (the old frontend had Layout.tsx and
 * this hook both doing that -- two sources of truth for the same thing).
 */
class ActivityStore {
  private state: ActivityMap = {};
  private listeners = new Set<() => void>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor() {
    wsClient.subscribe((event) => this.handle(event));
  }

  private handle(event: WsEvent) {
    if (event.event === "agent_message") {
      const to = event.to_agent as string;
      this.markBusy(to, {
        task: event.task as string | undefined,
        msgType: event.type as string | undefined,
        jobId: event.job_id as string | undefined,
      });
    } else if (event.event === "job_update") {
      const status = event.status as string;
      if (status === "done" || status === "failed" || status === "stopped") {
        this.clearJob(event.job_id as string);
      }
    }
  }

  private markBusy(agentId: string, info: Partial<AgentActivitySlot>) {
    if (!agentId) return;
    this.state = { ...this.state, [agentId]: { busy: true, since: Date.now(), ...info } };
    this.notify();

    const existing = this.timers.get(agentId);
    if (existing) clearTimeout(existing);
    this.timers.set(
      agentId,
      setTimeout(() => {
        const next = { ...this.state };
        delete next[agentId];
        this.state = next;
        this.notify();
      }, BUSY_TTL_MS)
    );
  }

  private clearJob(jobId: string) {
    let changed = false;
    const next: ActivityMap = {};
    for (const [id, slot] of Object.entries(this.state)) {
      if (slot.jobId === jobId) {
        changed = true;
        const t = this.timers.get(id);
        if (t) clearTimeout(t);
        this.timers.delete(id);
        continue;
      }
      next[id] = slot;
    }
    if (changed) {
      this.state = next;
      this.notify();
    }
  }

  private notify() {
    this.listeners.forEach((fn) => fn());
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  getState() {
    return this.state;
  }
}

const store = new ActivityStore();

export function useAgentActivity(): ActivityMap {
  const [state, setState] = useState(store.getState());
  useEffect(() => store.subscribe(() => setState(store.getState())), []);
  return state;
}
