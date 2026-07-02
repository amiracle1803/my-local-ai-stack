const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthInfo>("/health"),

  run: (goal: string, opts: RunOpts = {}) =>
    request<RunResult>("/run", { method: "POST", body: JSON.stringify({ goal, ...opts }) }),

  runQuick: (goal: string) =>
    request<RunResult>("/run/quick", { method: "POST", body: JSON.stringify({ goal }) }),

  agents: {
    list: () => request<AgentDef[]>("/agents/"),
    get: (id: string) => request<AgentDef>(`/agents/${id}`),
    ping: (id: string) => request<AgentPingResult>(`/agents/${id}/ping`, { method: "POST" }),
    create: (data: AgentCreateReq) =>
      request<{ status: string; agent_id: string }>("/agents/factory", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      request<{ status: string; agent_id: string }>(`/agents/${id}`, { method: "DELETE" }),
  },

  jobs: {
    list: (status?: string) => request<Job[]>(`/jobs/${status ? `?status=${status}` : ""}`),
    get: (id: string) => request<Job>(`/jobs/${id}`),
    create: (data: { type: string; title?: string; payload?: Record<string, unknown> }) =>
      request<{ id: string; status: string }>("/jobs/", { method: "POST", body: JSON.stringify(data) }),
    pause: (id: string) => request(`/jobs/${id}/pause`, { method: "POST" }),
    resume: (id: string) => request(`/jobs/${id}/resume`, { method: "POST" }),
    stop: (id: string) => request(`/jobs/${id}/stop`, { method: "POST" }),
    retry: (id: string) => request<{ id: string; status: string }>(`/jobs/${id}/retry`, { method: "POST" }),
    delete: (id: string) => fetch(`/api/jobs/${id}`, { method: "DELETE" }),
    saveNotes: (id: string, notes: string) =>
      request<{ id: string; notes: string }>(`/jobs/${id}/notes`, {
        method: "PATCH",
        body: JSON.stringify({ notes }),
      }),
  },

  llm: {
    models: () => request<ModelInfo[]>("/llm/models"),
  },

  obsidian: {
    notes: (limit = 100) => request<ObsidianNote[]>(`/obsidian/notes?limit=${limit}`),
    reindex: () => request<{ status: string; indexed: number }>("/obsidian/index", { method: "POST" }),
    search: (query: string, top_k = 5) =>
      request<{ query: string; results: ObsidianSearchResult[] }>("/obsidian/search", {
        method: "POST",
        body: JSON.stringify({ query, top_k }),
      }),
  },
};

// ── Types ────────────────────────────────────────────────────────────

export interface HealthInfo {
  status: string;
  service: string;
  models_loaded: number;
  agents_loaded: number;
}

export interface RunOpts {
  run_mode?: "sync" | "background";
  context?: Record<string, unknown>;
}

export interface RunResult {
  response?: string;
  job_id?: string;
  route?: string;
}

export interface AgentPingResult {
  agent_id: string;
  status: "ok" | "error";
  latency_ms: number;
  response?: string;
  error?: string;
  checked_at: string;
}

export type AgentLayer = "control" | "knowledge" | "action" | "platform";

export interface AgentDef {
  id: string;
  display_name: string;
  layer: AgentLayer;
  description: string;
  model_preference: string[];
  tools: string[];
  memory_scopes: string[];
  policies: string[];
  deletable?: boolean;
}

export interface AgentCreateReq {
  id: string;
  display_name: string;
  layer: string;
  description: string;
  tools: string[];
  model_preference: string[];
  memory_scopes: string[];
  policies: string[];
  system_prompt?: string;
}

export type JobStatus = "queued" | "running" | "paused" | "done" | "failed" | "stopped";

export interface Job {
  id: string;
  type: string;
  title?: string | null;
  status: JobStatus;
  progress: number;
  error: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  payload?: Record<string, unknown>;
  result?: { response?: string } | null;
}

export interface ModelInfo {
  name: string;
  provider: string;
  capabilities: string[];
  available: boolean;
}

export interface ObsidianNote {
  id: string;
  path: string;
  title: string;
  tags: string[];
  indexed_at: string;
}

export interface ObsidianSearchResult {
  id: string;
  path: string;
  title: string;
  score: number;
  snippet?: string | null;
}
