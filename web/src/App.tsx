import { useEffect, useMemo, useState } from "react";
import { api } from "./api";

type Run = {
  id: string;
  experiment: string;
  status: string;
  current_sweep: number;
  master_seed: number;
  horizon?: number;
};

type Point = {
  agent_id: string;
  lon: number | null;
  lat: number | null;
  stance: number;
  engagement: string;
  aware: boolean;
  name?: string;
};

function stanceColor(stance: number, aware: boolean): string {
  if (!aware) return "#94a3b8";
  if (stance <= -1.2) return "#9b2c2c";
  if (stance < 0) return "#c2410c";
  if (stance >= 1.2) return "#0f6e56";
  if (stance > 0) return "#3f6212";
  return "#64748b";
}

export default function App() {
  const [nAgents, setNAgents] = useState(20);
  const [sweeps, setSweeps] = useState(4);
  const [seed, setSeed] = useState(17);
  const [estimate, setEstimate] = useState<string>("");
  const [run, setRun] = useState<Run | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [points, setPoints] = useState<Point[]>([]);
  const [feed, setFeed] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [agentView, setAgentView] = useState<string>("");
  const [whyView, setWhyView] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const sweep = run?.current_sweep ?? -1;

  useEffect(() => {
    api.estimate({ n_agents: nAgents, horizon_sweeps: sweeps, seeds: 1, workers: 2 }).then(
      (e) => setEstimate(`~${e.total_minutes} min (${e.sec_per_sweep}s/sweep)`),
      () => setEstimate(""),
    );
  }, [nAgents, sweeps]);

  useEffect(() => {
    if (!run?.id) return;
    const t = setInterval(async () => {
      try {
        const r = await api.run(run.id);
        setRun(r);
        if (r.current_sweep >= 0) {
          const m = await api.metrics(run.id, r.current_sweep);
          const map: Record<string, number> = {};
          for (const row of m) map[row.name] = row.value;
          setMetrics(map);
          const mp = await api.map(run.id, r.current_sweep);
          setPoints(mp.points);
          const f = await api.feed(run.id, r.current_sweep);
          setFeed([
            ...f.deltas.map((d) => `Δ ${d.entity_id} [${d.status}] cause=${d.cause.join(",")}`),
            ...f.exposures.slice(0, 8).map((e) => `${e.source_kind}: ${e.content}`),
          ]);
        }
        if (r.status === "completed" || r.status === "failed") clearInterval(t);
      } catch (err) {
        setError(String(err));
      }
    }, 1500);
    return () => clearInterval(t);
  }, [run?.id]);

  async function startRun() {
    setBusy(true);
    setError("");
    setSelected(null);
    setAgentView("");
    setWhyView("");
    try {
      const created = await api.createExperiment({
        name: "maplewood-phone-ban",
        n_agents: nAgents,
        horizon_sweeps: sweeps,
        seeds: [seed],
      });
      const id = created.run_ids[0];
      const r = await api.run(id);
      setRun(r);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function openAgent(agentId: string) {
    if (!run) return;
    setSelected(agentId);
    const s = Math.max(0, run.current_sweep);
    const a = await api.agent(run.id, agentId, s);
    const w = await api.why(run.id, agentId, s);
    const stance = a.state.policy_stances?.phone_ban_6_12;
    setAgentView(
      [
        a.agent.demographics?.name,
        a.agent.narrative,
        `Anchors: ${(a.agent.anchors || []).join("; ")}`,
        `Stance: ${stance?.stance ?? "—"} (${stance?.engagement ?? "unaware"})`,
        `Mood/stress: ${a.state.fast?.mood ?? "—"} / ${a.state.fast?.stress ?? "—"}`,
        `Circle: ${a.circle.map((c) => c.label).join(", ")}`,
        "Memories:",
        ...a.memories.slice(0, 6).map((m) => `  w${m.sweep} [${m.type}] ${m.content}`),
      ].join("\n"),
    );
    setWhyView(
      JSON.stringify(
        {
          system1: w.inputs_and_system1,
          actions: w.actions,
          memories: w.memories.slice(0, 5),
        },
        null,
        2,
      ),
    );
  }

  const bounds = useMemo(() => {
    const lons = points.map((p) => p.lon).filter((x): x is number => x != null);
    const lats = points.map((p) => p.lat).filter((x): x is number => x != null);
    if (!lons.length || !lats.length) {
      return { minLon: -74.28, maxLon: -74.22, minLat: 40.72, maxLat: 40.78 };
    }
    return {
      minLon: Math.min(...lons),
      maxLon: Math.max(...lons),
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
    };
  }, [points]);

  return (
    <div className="app">
      <header className="brand">
        <h1>AgentSimCity</h1>
        <span>Generative social simulation — scenarios, not forecasts</span>
      </header>

      <div className="layout">
        <aside className="panel">
          <h2>Run setup</h2>
          <div className="field">
            <label>Agents</label>
            <input
              type="number"
              value={nAgents}
              min={5}
              max={200}
              onChange={(e) => setNAgents(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Sweeps</label>
            <input
              type="number"
              value={sweeps}
              min={1}
              max={52}
              onChange={(e) => setSweeps(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label>Seed</label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </div>
          <p className="meta">Estimate: {estimate || "…"}</p>
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <button onClick={startRun} disabled={busy}>
              {busy ? "Starting…" : "Start Maplewood phone-ban"}
            </button>
          </div>
          {error && <p className="error">{error}</p>}
          {run && (
            <p className="meta">
              Run <span className="pill">{run.id.slice(0, 8)}</span> · {run.status} · sweep{" "}
              {run.current_sweep}
              {run.horizon != null ? ` / ${run.horizon - 1}` : ""}
            </p>
          )}
        </aside>

        <main className="panel">
          <h2>Live run</h2>
          <div className="metrics">
            <div className="metric">
              <strong>{((metrics.awareness ?? 0) * 100).toFixed(0)}%</strong>
              <span>Awareness</span>
            </div>
            <div className="metric">
              <strong>{(metrics.stance_mean ?? 0).toFixed(2)}</strong>
              <span>Mean stance</span>
            </div>
            <div className="metric">
              <strong>{((metrics.engaged_share ?? 0) * 100).toFixed(0)}%</strong>
              <span>Engaged+</span>
            </div>
          </div>

          <div className="map" aria-label="Agent map">
            {points.map((p) => {
              if (p.lon == null || p.lat == null) return null;
              const x =
                ((p.lon - bounds.minLon) / Math.max(1e-6, bounds.maxLon - bounds.minLon)) * 100;
              const y =
                (1 - (p.lat - bounds.minLat) / Math.max(1e-6, bounds.maxLat - bounds.minLat)) *
                100;
              return (
                <button
                  key={p.agent_id}
                  className="dot"
                  title={`${p.name ?? p.agent_id} · stance ${p.stance}`}
                  style={{
                    left: `${x}%`,
                    top: `${y}%`,
                    background: stanceColor(p.stance, p.aware),
                    outline: selected === p.agent_id ? "2px solid #1a2332" : undefined,
                  }}
                  onClick={() => openAgent(p.agent_id)}
                />
              );
            })}
          </div>

          <h3 style={{ marginTop: "1rem", marginBottom: "0.4rem" }}>Feed</h3>
          <ul className="feed">
            {feed.length === 0 && <li>Waiting for sweep events…</li>}
            {feed.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>

          {selected && (
            <div className="inspector">
              <h3>Agent inspector · week {Math.max(0, sweep)}</h3>
              <pre>{agentView}</pre>
              <h3>Why-chain</h3>
              <pre>{whyView}</pre>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
