const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string }>("/health"),
  places: () => req<Array<{ id: string; name: string; slug: string }>>("/places"),
  estimate: (body: object) =>
    req<{ total_minutes: number; sec_per_sweep: number }>("/estimate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createExperiment: (body: object) =>
    req<{ run_ids: string[]; experiment: string }>("/experiments", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runs: () =>
    req<
      Array<{
        id: string;
        experiment: string;
        status: string;
        current_sweep: number;
        master_seed: number;
      }>
    >("/runs"),
  run: (id: string) =>
    req<{
      id: string;
      status: string;
      current_sweep: number;
      horizon?: number;
      experiment: string;
      master_seed: number;
    }>(`/runs/${id}`),
  metrics: (id: string, sweep: number) =>
    req<Array<{ name: string; value: number; segment: string }>>(
      `/runs/${id}/sweeps/${sweep}/metrics`,
    ),
  map: (id: string, sweep: number) =>
    req<{
      points: Array<{
        agent_id: string;
        lon: number | null;
        lat: number | null;
        stance: number;
        engagement: string;
        aware: boolean;
        name?: string;
      }>;
    }>(`/runs/${id}/sweeps/${sweep}/map`),
  feed: (id: string, sweep: number) =>
    req<{
      deltas: Array<{ entity_id: string; cause: string[]; status: string; change: object }>;
      exposures: Array<{ content: string; source_kind: string; agent_id: string }>;
    }>(`/runs/${id}/sweeps/${sweep}/feed`),
  agent: (runId: string, agentId: string, sweep?: number) =>
    req<{
      agent: {
        id: string;
        demographics: Record<string, unknown>;
        narrative: string;
        anchors: string[];
      };
      state: {
        policy_stances?: Record<string, { stance?: number; engagement?: string; aware?: boolean }>;
        fast?: { mood?: number; stress?: number };
      };
      memories: Array<{ sweep: number; content: string; type: string }>;
      circle: Array<{ key: string; label: string; sphere: string }>;
    }>(`/runs/${runId}/agents/${agentId}${sweep != null ? `?sweep=${sweep}` : ""}`),
  why: (runId: string, agentId: string, sweep: number) =>
    req<{
      inputs_and_system1: Array<{ route: string; escalated_by?: string; input_ref: object }>;
      actions: Array<{ type: string; intent_text: string; outcome?: object }>;
      memories: Array<{ content: string }>;
    }>(`/runs/${runId}/agents/${agentId}/why?sweep=${sweep}`),
};
