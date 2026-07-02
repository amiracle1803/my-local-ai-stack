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
    request<RunResult>("/run", {
      method: "POST",
      body: JSON.stringify({ goal, ...opts }),
    }),

  runQuick: (goal: string, system?: string) =>
    request<RunResult>("/run/quick", {
      method: "POST",
      body: JSON.stringify({ goal, system }),
    }),

  agents: {
    list: () => request<AgentDef[]>("/agents/"),
    get: (id: string) => request<AgentDef>(`/agents/${id}`),
    ping: (id: string) =>
      request<AgentPingResult>(`/agents/${id}/ping`, { method: "POST" }),
    create: (data: AgentCreateReq) =>
      request<{ status: string; agent_id: string }>("/agents/factory", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },

  jobs: {
    list: (status?: string) =>
      request<Job[]>(`/jobs/${status ? `?status=${status}` : ""}`),
    get: (id: string) => request<Job>(`/jobs/${id}`),
    create: (data: { type: string; title?: string; payload?: Record<string, unknown> }) =>
      request<{ id: string; status: string }>("/jobs/", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    update: (id: string, data: { title?: string; type?: string }) =>
      request<Job>(`/jobs/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
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
    test: () => request<{ status: string; response: string }>("/llm/test"),
  },

  metrics: {
    agents: () => request<AgentMetric[]>("/metrics/agents").catch(() => []),
    models: () => request<ModelMetric[]>("/metrics/models").catch(() => []),
  },

  system: {
    providerHealth: () =>
      request<ProviderHealthResponse>("/system/health/providers").catch(
        () => ({ providers: [], total: 0, healthy: 0 })
      ),
    runBackup: () =>
      request<{ ok: boolean; dir?: string; tables?: Record<string, number>; timestamp?: string; error?: string }>(
        "/system/backup/run",
        { method: "POST" }
      ),
    backupStatus: () =>
      request<{ last_backup: string | null }>("/system/backup/status").catch(
        () => ({ last_backup: null })
      ),
  },

  obsidian: {
    notes: (limit = 100) => request<ObsidianNote[]>(`/obsidian/notes?limit=${limit}`),
    reindex: () =>
      request<{ status: string; indexed: number }>("/obsidian/index", { method: "POST" }),
    search: (query: string, top_k = 5) =>
      request<{ query: string; results: ObsidianSearchResult[] }>("/obsidian/search", {
        method: "POST",
        body: JSON.stringify({ query, top_k }),
      }),
  },
};

// ── Types ──────────────────────────────────────────────────────────────────────

export interface HealthInfo {
  status: string;
  service: string;
  models_loaded: number;
  agents_loaded: number;
}

export interface RunOpts {
  risk_level?: RiskLevel;
  review_policy?: ReviewPolicyPreset;
  run_mode?: "sync" | "background";
  context?: Record<string, unknown>;
}

export interface RunResult {
  response: unknown;
  route?: string;
  conversation_id?: string;
  job_id?: string;
}

export interface AgentPingResult {
  agent_id: string;
  status: "ok" | "error";
  latency_ms: number;
  response?: string;
  error?: string;
  checked_at: string;
}

export interface AgentDef {
  id: string;
  display_name: string;
  layer: "control" | "knowledge" | "action" | "platform";
  description: string;
  model_preference: string[];
  tools: string[];
  memory_scopes: string[];
  policies: string[];
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

export interface Job {
  id: string;
  type: string;
  title?: string | null;
  status: TaskStatus;
  progress: number;
  error: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  payload?: Record<string, unknown>;
  result?: unknown;
}

export interface ModelInfo {
  name: string;
  provider: string;
  capabilities: string[];
  available: boolean;
}

export interface AgentMetric {
  agent_id: string;
  call_count: number;
  avg_latency_ms: number;
  successes: number;
  failures: number;
}

export interface ModelMetric {
  model_used: string;
  call_count: number;
  avg_latency_ms: number;
}

// ── Domain types ──────────────────────────────────────────────────────────────

export type TaskStatus =
  | "queued"
  | "running"
  | "paused"
  | "done"
  | "failed"
  | "stopped";

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type ReviewPolicyPreset = "low_risk_quick" | "medium_risk" | "high_risk";
export type ReviewDimension = "factual" | "safety" | "code_quality" | "style" | "cost";
export type ReviewVerdict = "approve" | "revise" | "block";

export interface ReviewScore {
  dimension: ReviewDimension;
  score: number;
  verdict: ReviewVerdict;
  feedback: Array<{ severity: "high" | "medium" | "low"; message: string }>;
}

export const RISK_POLICY: Record<RiskLevel, ReviewPolicyPreset> = {
  low: "low_risk_quick",
  medium: "medium_risk",
  high: "high_risk",
  critical: "high_risk",
};

export const POLICY_LABELS: Record<ReviewPolicyPreset, string> = {
  low_risk_quick: "Quick (1 round, auto-approve)",
  medium_risk: "Standard (2–3 rounds, optional human gate)",
  high_risk: "Strict (3–5 rounds, mandatory human approval)",
};

export interface ProviderStatus {
  name: string;
  provider: string;
  status: "healthy" | "degraded" | "down";
  latency_ms: number;
  checked_at: string;
}

export interface ProviderHealthResponse {
  providers: ProviderStatus[];
  total: number;
  healthy: number;
}

export interface ObsidianNote {
  id: string;
  path: string;
  title: string;
  tags: string[];   // backend now returns a parsed array
  indexed_at: string;
}

export interface ObsidianSearchResult {
  id: string;
  path: string;
  title: string;
  score: number;
  snippet?: string | null;
}
