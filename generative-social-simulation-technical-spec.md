# Generative Social Simulation — Detailed Technical Specification


|        |                                                                                           |
| ------ | ----------------------------------------------------------------------------------------- |
| Status | Draft v0.2                                                                                |
| Date   | 2026-10-29                                                                                |
| Source | Design spec plus the AgentSimCity implementation                                          |
| Scope  | MVP (Phase 1) in full detail; Phases 2–3 specified at interface level                     |


This document turns the design spec into an engineering specification: components, data model, algorithms, interfaces, model contracts, configuration, testing and milestones. Where the design spec gives a default "to calibrate", this document gives the starting value and names the config key that holds it. Where a decision is still open, it is listed in §20 rather than guessed.

---



## Contents

1. Goals, non-goals and terminology
2. System overview
3. Repository and service layout
4. Configuration
5. Data model (Postgres)
6. Determinism, seeding and caching
7. The sweep engine
8. Agents: profile, state and update rules
9. Memory
10. System 1 (TypeSafe Jev / System One)
11. System 2 and other LLM roles (stubs or Ollama)
12. Social world: circles, contexts, messages and exposures
13. World model: canon, rules engine, world master, resolver
14. Institutions and media
15. Randomness engine
16. Population generation
17. Place import (city packs)
18. API and environment interface
19. Testing, validation and observability
20. Open questions
21. Milestones and acceptance criteria

Appendix A. JSON schemas for model outputs
Appendix B. Prompt templates
Appendix C. Default parameters

---



## 1. Goals, non-goals and terminology



### 1.1 Goals

- Simulate a sampled population of one real or composite place, one simulated week per sweep, for 12–52 sweeps.
- Let a policy enter as a change to world rules; let reactions emerge from agents noticing, appraising, acting and spreading information.
- Produce scenarios and mechanisms (ensembles, cascades, tipping points, branch comparisons), not forecasts.
- Be fully reproducible: any run can be replayed exactly from its seed and the model-call cache.
- Swap any model role without code changes elsewhere (`config/models.yaml` + `config/defaults.yaml`). Default System 1 is hosted TypeSafe Jev; LLM roles default to deterministic stubs and can be pointed at local Ollama (`llama3.2:3b`).
- Make every agent decision traceable to its inputs, memories and stored reasoning.



### 1.2 Non-goals (MVP)

- National or multi-city simulations (future: several local worlds linked together).
- Real-time speed. A sweep may take tens of minutes.
- Simulating real, identifiable individuals.
- Presenting outputs as public-opinion forecasts or evidence of consent.



### 1.3 Terminology


| Term              | Meaning                                                                                               |
| ----------------- | ----------------------------------------------------------------------------------------------------- |
| Place / city pack | A versioned bundle of geography, jurisdictions, institutions, local texture and sources for one place |
| Population        | A set of agents generated for one place at one sampling ratio, checked and frozen                     |
| Agent             | One simulated individual. Carries a weight = number of real residents it stands for                   |
| Run               | One execution of a population + policy package + config + seed for N sweeps                           |
| Branch            | A run forked from a parent run at sweep *t* with an intervention applied                              |
| Ensemble          | A set of runs that differ only by master seed                                                         |
| Sweep             | One simulated week; the engine's unit of time                                                         |
| Canon             | The world's single source of truth: entities, ledgers, routines                                       |
| Delta             | A proposed change to the canon, with cause, checked before commit                                     |
| Context           | A shared setting connecting agents: workplace, school, neighborhood, online group, media audience     |
| Circle            | An agent's social-circle subagent and its roster of contacts                                          |
| Exposure          | An item reaching an agent through a context or medium (not a direct message from another agent)       |
| System 1          | Fast typed classifier (TypeSafe Jev System One API) run on every input                                |
| System 2          | In-character LLM appraisal and decision, run only on escalated inputs                                 |
| World master      | LLM role that resolves open-ended actions and proposes world deltas                                   |


---



## 2. System overview

```
             ┌─────────────────┐  ┌───────────────────┐  ┌──────────────────┐
  inputs     │ Policy package  │  │ Place + population│  │ Randomness engine│
             └────────┬────────┘  └─────────┬─────────┘  └────────┬─────────┘
                      └───────────────┬─────┴─────────────────────┘
                                      ▼
   ┌──────────────────────────── Sweep engine (per run) ─────────────────────────┐
   │  World model         Agent minds            Message bus        Institutions │
   │  (canon, rules,      (System 1 → System 2,  (circle, group,    and media    │
   │   world master,       circles, memory,       formal msgs,                   │
   │   resolver)           reflection)            exposures)                     │
   └──────────────┬───────────────────────────────────────────────┬──────────────┘
                  │ writes each sweep                             │ model calls
                  ▼                                               ▼
        ┌──────────────────┐   jobs (SKIP LOCKED)        ┌────────────────────┐
        │ Postgres         │ ◄────────────────────────►  │ Model workers      │
        │ pgvector, PostGIS│                             │ TypeSafe Jev ·     │
        │                  │                             │ OpenJev · Ollama   │
        └────────┬─────────┘                             └────────────────────┘
                 │ LISTEN/NOTIFY, REST
                 ▼
        ┌──────────────────┐
        │ API (FastAPI)    │ ◄──► Web app (React, MapLibre + deck.gl, Sigma.js)
        └──────────────────┘
```

**Processes**


| Process         | Count                          | Responsibility                                                             |
| --------------- | ------------------------------ | -------------------------------------------------------------------------- |
| `api`           | 1+                             | REST and WebSocket API; enqueues runs; serves interface                    |
| `engine`        | 1 per active run               | Owns the sweep loop for one run; holds the sweep's working state in memory |
| `model-worker`  | N (= parallel workers setting) | Pulls model-call jobs; calls TypeSafe / OpenJev / Ollama; writes cache     |
| `import-worker` | 1+                             | Runs place-import pipelines and population builds                          |
| `postgres`      | 1                              | All persistent state                                                       |
| `ollama`        | 0–1                            | Optional. Serves Llama 3.2 and the embedding model (`:11434`)              |
| TypeSafe Jev    | hosted                         | Default System 1: `POST https://api.typesafe.ai/v1/systemone`              |
| `openjev`       | 0–1                            | Optional local System One server (`:3000`); sim API stays on `:8000`       |


The engine talks to models only through `sim/llm/gateway.py`. For stubs, System One (`kind: system_one`) and Ollama, the MVP executes the call **inline** and writes `model_calls`; other kinds enqueue jobs for `model-worker`. Replays are served entirely from cache (`ReplayCacheMiss` on a miss).

---



## 3. Repository and service layout

```
sim/
  pyproject.toml
  config/
    defaults.yaml            # Appendix C
    models.yaml              # model roles → endpoints
  sim/
    core/                    # ids, seeding, clock, errors, logging
    db/                      # SQLAlchemy models, migrations (Alembic), queue
    engine/
      sweep.py               # the nine-step loop (§7)
      phases/                # one module per step
      collisions.py
    agents/
      profile.py             # schema + rendering (§8)
      update_rules.py
      memory.py              # (§9)
    system1/                 # System One client (TypeSafe/OpenJev), question sets, routing (§10)
    llm/                     # gateway, stubs, Ollama client, prompts, schema validation (§11)
    social/                  # circles, contexts, bus, exposures (§12)
    world/                   # canon, rules engine, world master, resolver, deltas (§13)
    institutions/            # (§14)
    randomness/              # channels, shock library (§15)
    population/              # skeleton, fusion, variation, narratives, checks (§16)
    places/                  # import pipeline, MRP, report (§17)
    metrics/                 # per-sweep aggregates, ensemble stats
    api/                     # FastAPI app (§18)
    workers/                 # model-worker, import-worker entrypoints
  web/                       # React app
  tests/
    unit/ integration/ golden/ fidelity/
  docker-compose.yml
```

Language: Python 3.12. Key libraries: SQLAlchemy 2 + Alembic, psycopg 3, pydantic v2, numpy, networkx (in-sweep computation), Mesa (agent registry and seeded activation order only; the engine owns the loop), FastAPI, httpx. Web: React, TypeScript, MapLibre GL + deck.gl, Sigma.js.

---



## 4. Configuration

All behavior parameters live in YAML, merged in this order: `defaults.yaml` → place pack overrides → experiment config → run overrides. The merged config is stored verbatim in `runs.config` (JSONB) and hashed into `runs.config_hash`; a replay must use the identical config.

```yaml
# experiment.yaml (illustrative)
experiment:
  name: maplewood-phone-ban
  place_pack: maplewood@3
  population:
    sampling_ratio: 100          # 1 agent : 100 residents
    full_tier_share: 0.05
  policy_package: phone_ban_6_12@3
  horizon_sweeps: 12
  seeds: [17, 18, 19, 20, 21]
  mode: closed                   # closed | open
  chaos_level: 1.0
  scripted_shocks: []
models:
  system1: typesafe-hosted      # default; needs TYPESAFE_API_KEY
  system2: stub-llm             # or llama3.2-3b once Ollama is running
  circle: stub-llm
  world_master: stub-llm
  institutions: stub-llm
  embeddings: stub-embed        # or nomic-embed-text
compute:
  workers: 2
```

```yaml
# config/models.yaml (current catalog)
typesafe-hosted:
  kind: system_one
  base_url: https://api.typesafe.ai/v1/systemone
  model: jev-latest
  model_digest: jev-latest
  fallback_fixtures: true       # offline / missing key → recorded fixtures
  timeout_s: 60
openjev-local:
  kind: system_one
  base_url: http://localhost:3000/v1/systemone
  model: openjev
  timeout_s: 120
openjev-fixtures:
  kind: system_one
  use_fixtures: true
llama3.2-3b:
  kind: ollama_chat
  base_url: http://127.0.0.1:11434
  model: llama3.2:3b
  options: { temperature: 0.7, num_ctx: 8192 }
nomic-embed-text:
  kind: ollama_embed
  base_url: http://127.0.0.1:11434
  model: nomic-embed-text
  dim: 768
stub-system1: { kind: stub_system1, model: stub-system1 }
stub-llm:     { kind: stub_llm, model: stub-llm }
stub-embed:   { kind: stub_embed, model: stub-embed, dim: 768 }
```

Secrets live in `.env` (never in YAML): `TYPESAFE_API_KEY` (alias `TYPEFACE_API_KEY`) for hosted Jev; optional `OPENJEV_TOKEN` / `SHIM_TOKEN` for a token-gated local server; `SIM_DATABASE_URL` for Postgres; `HF_TOKEN` only if downloading local OpenJev MLX weights.

Every model entry records `model` + `model_digest` in `runs.model_manifest`. A replay against a different digest is refused unless the run is marked `rerun` rather than `replay`.

---



## 5. Data model (Postgres)

Postgres 16 with extensions `vector` (pgvector), `postgis`, `pgcrypto`. All ids are UUIDv7 (time-ordered) unless noted. All state tables are **append-only**; "current state" is the row with the highest `sweep` ≤ the sweep of interest for the run's lineage (§5.4).

### 5.1 Places and world

```sql
CREATE TABLE places (
  id            uuid PRIMARY KEY,
  slug          text NOT NULL,             -- 'maplewood'
  version       int  NOT NULL,             -- pack version
  name          text NOT NULL,
  boundary      geometry(MultiPolygon,4326) NOT NULL,
  jurisdictions jsonb NOT NULL,            -- [{id,kind,name,geom_ref,included}]
  sources       jsonb NOT NULL,            -- [{layer,source,url,as_of,license}]
  import_report jsonb,                     -- §17.3
  status        text NOT NULL CHECK (status IN ('importing','review','approved','superseded')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (slug, version)
);

CREATE TABLE world_entities (             -- canon, versioned by sweep
  entity_id   text NOT NULL,              -- stable id, e.g. 'school_maplewood_middle'
  place_id    uuid NOT NULL REFERENCES places,
  run_id      uuid,                       -- NULL = baseline canon of the pack
  sweep       int  NOT NULL,              -- -1 = baseline
  kind        text NOT NULL,              -- place|institution|business|service|group|media|zone|route
  name        text NOT NULL,
  fields      jsonb NOT NULL,             -- typed fields per kind (schema in sim/world/kinds.py)
  description text NOT NULL,              -- free text, LLM-maintained
  geom        geometry(Geometry,4326),
  invented    boolean NOT NULL DEFAULT false,
  sources     jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (place_id, entity_id, run_id, sweep)
);
CREATE INDEX ON world_entities USING gist (geom);

CREATE TABLE world_deltas (
  id           uuid PRIMARY KEY,
  run_id       uuid NOT NULL,
  sweep        int  NOT NULL,
  entity_id    text NOT NULL,
  change       jsonb NOT NULL,             -- {field, from, to} | {create:{...}} | {retire:true}
  description_update text,
  cause        text[] NOT NULL,            -- ['policy:...','action:<id>','aggregate:...','event:<id>']
  proposed_by  text NOT NULL,              -- world_master|rules_engine|institution:<id>|researcher
  confidence   real,
  status       text NOT NULL CHECK (status IN ('proposed','committed','rejected','returned')),
  check_results jsonb NOT NULL,            -- {contradiction, scale, cause, ...}
  model_call_id uuid
) PARTITION BY LIST (run_id);
```



### 5.2 Populations and agents

```sql
CREATE TABLE populations (
  id              uuid PRIMARY KEY,
  place_id        uuid NOT NULL REFERENCES places,
  sampling_ratio  int  NOT NULL,           -- residents per agent
  generator_config jsonb NOT NULL,
  seed            bigint NOT NULL,
  checks          jsonb,                   -- §16.7 results
  status          text NOT NULL CHECK (status IN ('building','burn_in','checking','frozen','failed')),
  baseline_sweep  int,                     -- last burn-in sweep
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agents (                      -- fixed tier only
  id            uuid PRIMARY KEY,
  population_id uuid NOT NULL REFERENCES populations,
  weight        real NOT NULL,             -- residents represented
  tier          text NOT NULL CHECK (tier IN ('full','standard')),
  is_synthetic_tail boolean NOT NULL DEFAULT false,
  demographics  jsonb NOT NULL,            -- age, sex, race_eth, education, income, occupation, household...
  traits        jsonb NOT NULL,            -- big5 scores + text
  values        jsonb NOT NULL,            -- ranked values, moral lines
  voice         jsonb NOT NULL,            -- fluency, tics, answer length, polish ceiling
  narrative     text NOT NULL,             -- biography, formative experiences
  anchors       text[] NOT NULL,           -- consistency anchors
  footprint     jsonb NOT NULL,            -- roles, places, money flows, institutions (entity ids)
  home_geom     geometry(Point,4326),
  donors        jsonb NOT NULL,            -- survey donor record ids per layer (provenance, never shown)
  civic_baseline real NOT NULL,            -- caps escalation ladder (0..1)
  attention_baseline real NOT NULL
);

CREATE TABLE agent_state (                 -- slow + fast tiers, one row per agent per sweep it changed
  run_id     uuid NOT NULL,
  agent_id   uuid NOT NULL,
  sweep      int  NOT NULL,
  tier       text NOT NULL,                -- promotion recorded here
  slow       jsonb NOT NULL,               -- attitudes, trust, identity_strength, goals, worries, self_narrative_additions
  fast       jsonb NOT NULL,               -- circumstances, mood, stress, concerns[], attention, civic_intent
  policy_stances jsonb NOT NULL,           -- {policy_id: PolicyStance} (§8.3)
  PRIMARY KEY (run_id, agent_id, sweep)
) PARTITION BY LIST (run_id);
```



### 5.3 Social world

```sql
CREATE TABLE contexts (
  id          uuid PRIMARY KEY,
  place_id    uuid NOT NULL,
  run_id      uuid,                        -- NULL = baseline; non-null = created in a run
  created_sweep int,
  kind        text NOT NULL CHECK (kind IN ('workplace','school','school_parents','school_students',
                                            'neighborhood','online_group','media_audience','institution')),
  entity_id   text,                        -- canon entity it belongs to
  name        text NOT NULL,
  real_size   int,                         -- real-population members (for scaling)
  params      jsonb NOT NULL               -- feed_probability, activity, etc.
);

CREATE TABLE memberships (
  run_id      uuid,                        -- NULL = baseline
  context_id  uuid NOT NULL,
  agent_id    uuid NOT NULL,
  role        text,                        -- employee, student, parent, member, admin
  from_sweep  int NOT NULL,
  to_sweep    int,                         -- NULL = current
  PRIMARY KEY (context_id, agent_id, from_sweep, run_id)
);

CREATE TABLE circle_contacts (
  id            uuid PRIMARY KEY,
  agent_id      uuid NOT NULL,
  contact_key   text NOT NULL,             -- 'beth', 'coworkers_er'
  label         text NOT NULL,             -- 'Beth, older sister'
  sphere        text NOT NULL CHECK (sphere IN ('household','close','work_school','community','online')),
  context_id    uuid,                      -- grounding context, if any
  match_filter  jsonb,                     -- grounding filter for contacts without a context
  stance_tendency text,
  description   text NOT NULL,
  aggregate     boolean NOT NULL DEFAULT false,  -- true = stands for several people ("five ER nurses")
  UNIQUE (agent_id, contact_key)
);

CREATE TABLE circle_state (                -- closeness and contact memory per sweep
  run_id     uuid NOT NULL,
  contact_id uuid NOT NULL,
  sweep      int  NOT NULL,
  closeness  real NOT NULL,
  contact_memory text NOT NULL,            -- rolling summary of what was discussed
  PRIMARY KEY (run_id, contact_id, sweep)
) PARTITION BY LIST (run_id);

CREATE TABLE messages (
  id          uuid PRIMARY KEY,
  run_id      uuid NOT NULL,
  sweep       int  NOT NULL,
  sender      text NOT NULL,               -- 'agent:<id>' | 'institution:<id>' | 'media:<id>' | 'circle:<agent>:<contact>'
  recipients  jsonb NOT NULL,              -- {circle:[contact_keys]} | {group:<context_id>} | {institution:<id>}
  channel     text NOT NULL CHECK (channel IN ('in_person','call','text','group_post','formal','broadcast')),
  content     text NOT NULL,
  intent      text NOT NULL,
  stance_expressed smallint,
  emotion     text,
  topic_tags  text[] NOT NULL DEFAULT '{}',
  reply_to    uuid,
  lineage     uuid,                        -- root message id
  engagement  int NOT NULL DEFAULT 0       -- replies/reactions, drives visibility
) PARTITION BY LIST (run_id);

CREATE TABLE exposures (
  id          uuid PRIMARY KEY,
  run_id      uuid NOT NULL,
  sweep_created int NOT NULL,
  deliver_sweep int NOT NULL,              -- = sweep_created + 1
  agent_id    uuid NOT NULL,               -- recipient
  source_kind text NOT NULL CHECK (source_kind IN ('circle_spread','group_post','media','institution','world','event')),
  message_id  uuid,
  context_id  uuid,
  path        jsonb NOT NULL,              -- [{agent|context|circle_step}] for cascade tracing
  content     text NOT NULL,               -- as re-voiced for this recipient, may be distorted
  distorted   boolean NOT NULL DEFAULT false,
  status      text NOT NULL CHECK (status IN ('pending','read','expired','ignored')),
  expires_sweep int NOT NULL               -- deliver_sweep + 2
) PARTITION BY LIST (run_id);
```



### 5.4 Runs, decisions, actions, events

```sql
CREATE TABLE runs (
  id            uuid PRIMARY KEY,
  experiment    text NOT NULL,
  population_id uuid NOT NULL,
  policy_package_id uuid NOT NULL,
  master_seed   bigint NOT NULL,
  config        jsonb NOT NULL,
  config_hash   text NOT NULL,
  model_manifest jsonb NOT NULL,
  parent_run_id uuid REFERENCES runs,
  fork_sweep    int,                       -- branch reads parent rows for sweep <= fork_sweep
  intervention  jsonb,                     -- applied at fork_sweep + 1
  status        text NOT NULL CHECK (status IN ('queued','running','paused','completed','failed','cancelled')),
  current_sweep int NOT NULL DEFAULT -1,
  kind          text NOT NULL CHECK (kind IN ('run','replay','rerun')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE policy_packages (
  id        uuid PRIMARY KEY,
  slug      text NOT NULL, version int NOT NULL,
  place_id  uuid NOT NULL,
  spec      jsonb NOT NULL,                -- §13.2
  UNIQUE (slug, version)
);

CREATE TABLE system1_decisions (
  id          uuid PRIMARY KEY,
  run_id      uuid NOT NULL, sweep int NOT NULL, agent_id uuid NOT NULL,
  input_ref   jsonb NOT NULL,              -- {kind, id}
  question_set text NOT NULL,              -- 'notice_route_v1'
  answers     jsonb NOT NULL,              -- {question: {value, probs, confidence}}
  route       text NOT NULL CHECK (route IN ('ignore','habit','escalate')),
  escalated_by text,                       -- 'route'|'low_confidence'|'trigger:<name>'
  model_call_id uuid NOT NULL
) PARTITION BY LIST (run_id);

CREATE TABLE actions (
  id          uuid PRIMARY KEY,
  run_id      uuid NOT NULL, sweep int NOT NULL, agent_id uuid NOT NULL,
  source      text NOT NULL CHECK (source IN ('system2','habit','circle')),
  type        text NOT NULL,               -- §11.4 action menu
  intent_text text NOT NULL,
  params      jsonb NOT NULL,
  validation  jsonb NOT NULL,              -- {ok, reason}
  resolver    text,                        -- rules|world_master|institution|bus
  outcome     jsonb,                       -- {status: granted|refused|partial|done, detail}
  delta_ids   uuid[] NOT NULL DEFAULT '{}',
  model_call_id uuid
) PARTITION BY LIST (run_id);

CREATE TABLE events (
  id        uuid PRIMARY KEY,
  run_id    uuid NOT NULL, sweep int NOT NULL,
  channel   text NOT NULL,                 -- life_event|shock|amplification|misperception|ambient|scripted
  target    jsonb NOT NULL,                -- {agent_id} | {entity_id} | {context_id} | {world:true}
  draw      jsonb NOT NULL,                -- the random draw (type, magnitude)
  realized  jsonb,                         -- world master's concrete version, if any
  model_call_id uuid
) PARTITION BY LIST (run_id);

CREATE TABLE memories (
  id         uuid PRIMARY KEY,
  run_id     uuid NOT NULL,                -- burn-in memories: population's burn-in run id
  agent_id   uuid NOT NULL,
  sweep      int NOT NULL,
  type       text NOT NULL CHECK (type IN ('experience','message_received','message_sent','action','media','reflection','summary')),
  content    text NOT NULL,
  source     text,
  importance smallint NOT NULL CHECK (importance BETWEEN 1 AND 10),
  valence    real NOT NULL CHECK (valence BETWEEN -1 AND 1),
  policy_id  text,
  embedding  vector(768) NOT NULL,
  dropped_sweep int,                       -- set when forgotten/compressed
  summarized_into uuid
) PARTITION BY LIST (run_id);
-- per-partition: CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);
```

Plus `model_calls` (§6.3), `jobs` (§7.6), `probes` (§18.3) and `metrics` (§19.4).

### 5.5 Lineage reads (branches)

A branch run `R` with parent `P` and `fork_sweep = f` resolves state as: rows of `R` for sweeps > f, else rows of `P` for sweeps ≤ f (recursively up the parent chain). Implemented as a SQL function `lineage(run_id) RETURNS TABLE(run_id uuid, max_sweep int)` and used by views `v_agent_state_at(run, sweep)`, `v_canon_at(run, sweep)`, etc. Parent partitions are never copied.

### 5.6 Partitioning and retention

Run-scoped tables are list-partitioned by `run_id`; the engine creates partitions at run start. Completed ensembles can be exported to Parquet (`sim export --run <id>`) and their partitions detached. Volume estimate per run: `agents × sweeps × ~10` System 1 rows; 200 agents × 12 sweeps ≈ 24k rows (MVP); 11,000 agents × 26 sweeps ≈ 2.9M rows.

---



## 6. Determinism, seeding and caching



### 6.1 Seed derivation

```
seed(run, channel, sweep, *keys) = int.from_bytes(
    sha256(f"{master_seed}|{channel}|{sweep}|{'|'.join(keys)}").digest()[:8], "big")
```

Channels: `order`, `life_events`, `shocks`, `amplification`, `misperception`, `behavior`, `visibility`, `circle_spread`, `resolver`, `llm`. Each random decision draws from a `numpy.random.Generator(PCG64(seed(...)))` created for that exact decision; no shared mutable RNG is passed around. This makes results independent of processing order and worker count.

Branches inherit the parent's master seed, so sweeps after the fork differ only where the intervention changes inputs.

### 6.2 LLM determinism

Every LLM call sets `options.seed = seed(run, 'llm', sweep, role, agent_or_entity, call_index)` and the configured temperature. Local model output is not guaranteed bit-identical across hardware, so determinism is guaranteed by the cache, not by the model.

### 6.3 Model-call cache

```sql
CREATE TABLE model_calls (
  id          uuid PRIMARY KEY,
  cache_key   text NOT NULL UNIQUE,        -- sha256 of canonical JSON below
  role        text NOT NULL,               -- system1|system2|circle|world_master|institution|narrative|embed|judge
  model       text NOT NULL, model_digest text NOT NULL,
  request     jsonb NOT NULL,              -- full prompt/messages, schema, options
  response    jsonb NOT NULL,
  latency_ms  int NOT NULL,
  attempts    smallint NOT NULL,
  valid       boolean NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

`cache_key = sha256(canonical_json({model, model_digest, role, request, options_incl_seed}))`.

- `kind = replay`: every call must hit the cache; a miss fails the run with `ReplayCacheMiss`.
- `kind = run`/`rerun`: cache hits are reused (identical inputs give identical outputs), misses are executed.

---



## 7. The sweep engine



### 7.1 Loop

```python
def run(run_id):
    ctx = RunContext.load(run_id)               # config, population, policy, lineage
    for s in range(ctx.start_sweep, ctx.horizon):
        if ctx.pause_requested(): ctx.set_status('paused'); return
        sweep(ctx, s)
        ctx.commit_sweep(s)                    # single transaction: all rows for sweep s
        notify('sweep_done', run_id, s)
    ctx.set_status('completed')
```

A sweep either commits entirely or not at all. On crash, the engine resumes from `current_sweep + 1`; in-flight model calls already in the cache are reused.

### 7.2 The nine steps


| #   | Step                         | LLM?                                 | Reads                                             | Writes                                                     |
| --- | ---------------------------- | ------------------------------------ | ------------------------------------------------- | ---------------------------------------------------------- |
| 1   | Apply world rules            | world master (judgment calls)        | canon, policy, routines, last sweep's adaptations | ledgers, world deltas, direct-impact inputs                |
| 2   | Sample random events         | world master (realize ambient/shock) | randomness channels                               | events, inputs                                             |
| 3   | Deliver inputs               | no                                   | exposures with `deliver_sweep = s`, media items   | per-agent input queues                                     |
| 4   | System 1                     | TypeSafe Jev (System One)            | inputs, agent state vector                        | system1_decisions, habit actions                           |
| 5   | System 2 appraise and decide | System 2, circle subagent            | escalated agents' cards, memories, inputs         | interpretations, proposed state changes, intents, messages |
| 6   | Resolve actions              | world master (open-ended)            | intents                                           | actions, outcomes, deltas, messages, exposures for s+1     |
| 7   | Institutions respond         | institutions                         | aggregate signals                                 | statements, amendments, broadcast exposures for s+1        |
| 8   | Reflect and update           | System 2 (reflection)                | week's memories                                   | memories, agent_state (slow/fast), circle_state            |
| 9   | Log and measure              | no                                   | everything for s                                  | metrics                                                    |


Within each step, work for all agents is fanned out as jobs and awaited as a barrier. Nothing an agent produces in sweep *s* is visible to any other agent before step 3 of sweep *s+1*; so agents can be processed in parallel and the seeded activation order (`order` channel) is used only where order matters: collision batching (§13.6) and attention-limited reading ties.

### 7.3 Step details

**Step 1 — Apply world rules.**

1. Apply any policy package changes effective at `s` (rules, exemptions, schedule) and any queued intervention (branch).
2. Rules engine computes mechanical effects per agent from routines and ledgers (charges, enforcement events, schedule changes) → `Input(kind='direct_impact')`.
3. Apply last sweep's committed adaptations (route, schedule, enrollment changes) and recompute aggregates (traffic per zone, store customers, enrollment).
4. World master is called once per affected entity cluster for judgment calls defined by the policy package (`judgment_hooks`, §13.2), e.g. per-school enforcement strictness. Outputs are deltas.
5. Threshold checks on aggregates may emit events (§14).

**Step 2 — Sample random events.** Per §15. Life events become `Input(kind='life_event')` for the target agent and may change fast attributes or footprint through deltas. Shocks are realized by the world master into concrete descriptions and canon deltas.

**Step 3 — Deliver inputs.** Collect, per agent: direct impacts (step 1), events (step 2), exposures due this sweep, media items from sources in the agent's information diet published in s−1, circle replies pending. Expire exposures where `expires_sweep < s`.

**Step 4 — System 1.** For each agent, sort inputs by provisional priority `closeness × salience_hint` and process until the attention budget is spent (§10.5). Each processed input → one System 1 query (batched per agent where the API allows). Routes: ignore → memory (importance ≤ 3); habit → template action + bounded fast-state nudge; escalate → add to the agent's escalation set. An agent is "escalated this sweep" if its escalation set is non-empty.

**Step 5 — System 2.** One appraise-and-decide call per escalated agent, covering all its escalated inputs (Appendix A.1). If the output contains circle talk, the circle subagent is invoked (§12.2), up to four turns per conversation. Validated outputs become: proposed policy-stance updates (fast tier, applied in step 8), intents (step 6), messages (bus).

**Step 6 — Resolve actions.** Validate each intent against capability rules (§11.5). Route: mechanical → rules engine; open-ended → world master (batched by target entity for collisions); social (create/join group) → engine + world master reception judgment; formal → institution inbox; talk/post → message bus. Produce outcomes, deltas, messages and next-sweep exposures (§12.4).

**Step 7 — Institutions respond.** Evaluate thresholds in real-population terms (§14.2); for triggered institutions, call the institution LLM to draft the response and framing; produce statements (broadcast exposures for s+1), enforcement changes and — in open mode, within researcher limits — policy amendments effective s+1.

**Step 8 — Reflect and update.** Reflection call for agents escalated this sweep plus every agent whose `agent_index % 4 == s % 4` (each agent at least every four sweeps). Apply bounded slow-tier changes (§8.4). Apply fast-tier updates and decay for all agents. Check promotion (§16.5). Update circle closeness and contact memory. Run drift checks on the scheduled sweeps (§19.2).

**Step 9 — Log and measure.** Compute weighted metrics (§19.4) and write `metrics`. Notify the UI.

### 7.4 Inputs

```python
class Input(BaseModel):
    id: UUID
    kind: Literal['direct_impact','life_event','exposure','media','institution_notice','circle_reply','world_update']
    source: str                 # entity/agent/context/media id
    content: str                # one or two sentences as the agent would perceive it
    impact_magnitude: float     # 0..1, from rules engine or event
    policy_id: str | None
    closeness: float            # 0..1, sender closeness if any
    repeat_count: int           # times agent has seen this lineage/topic before
```



### 7.5 Run time estimate (shown in Run setup)

```
s1_calls      = agents × inputs_per_agent                     # default 10
llm_calls     = agents × esc_rate × 3                         # appraisal + reflection + circle
              + agents × full_share / 4                       # scheduled reflections (full tier)
              + world_master_calls + institution_calls        # default 20
sec_per_sweep = (llm_calls × t_llm + s1_calls × t_s1) / workers
total         = sec_per_sweep × sweeps × seeds
```

Defaults `t_llm = 3 s`, `t_s1 = 0.3 s` until benchmarked; after benchmarking, the estimator reads p50 latencies per role from `model_calls`.

### 7.6 Job queue

```sql
CREATE TABLE jobs (
  id         bigserial PRIMARY KEY,
  run_id     uuid NOT NULL, sweep int NOT NULL, phase smallint NOT NULL,
  role       text NOT NULL,
  payload    jsonb NOT NULL,
  cache_key  text NOT NULL,
  status     text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  attempts   smallint NOT NULL DEFAULT 0,
  locked_by  text, locked_at timestamptz,
  result_call_id uuid
);
CREATE INDEX ON jobs (status, role, id) WHERE status = 'queued';
```

Workers claim with `SELECT … FOR UPDATE SKIP LOCKED LIMIT n`. Before calling a model, a worker checks `model_calls.cache_key`. Stale locks (> 10 min) are reclaimed. The engine waits on `LISTEN job_done` with a polling fallback.

---



## 8. Agents: profile, state and update rules



### 8.1 Tiers


| Tier  | Storage                              | Who writes                                            | When                                                                                                                |
| ----- | ------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Fixed | `agents`                             | Population generator; researcher between runs         | Never during a run (exception: footprint via life-event deltas, recorded in `agent_state.fast.footprint_overrides`) |
| Slow  | `agent_state.slow`                   | Engine, from reflection proposals                     | Step 8 only, bounded                                                                                                |
| Fast  | `agent_state.fast`, `policy_stances` | Engine, from System 1 nudges, System 2 outputs, rules | Steps 4, 5 (applied in 8), 8 decay                                                                                  |




### 8.2 Slow and fast schemas (abridged)

```python
class Slow(BaseModel):
    attitudes: dict[str, float]          # issue -> -3..+3
    trust: dict[str, float]              # source/institution id -> 0..1
    identity_strength: dict[str, float]  # group -> 0..1
    goals: list[str]; worries: list[str]
    self_narrative_additions: list[tuple[int, str]]   # (sweep, line), append-only
    pending_evidence: dict[str, list[EvidenceItem]]   # accumulates toward slow changes

class Fast(BaseModel):
    circumstances: dict                  # employment, income band, health, household events
    mood: float                          # -1..1
    stress: float                        # 0..1
    concerns: list[Concern]              # {topic, salience 0..1}
    attention: float                     # remaining budget this sweep
    civic_intent: dict                   # vote_intent, meeting plans
    footprint_overrides: dict
```



### 8.3 Policy stance object

```python
class PolicyStance(BaseModel):
    policy_id: str
    aware: bool
    first_heard_sweep: int | None
    first_heard_from: str | None
    perceived_policy: str | None
    perceived_personal_impact: str | None
    perceived_risks: list[str] = []
    perceived_benefits: list[str] = []
    stance: float            # -3..+3
    certainty: float         # 0..1
    salience: float          # 0..1
    engagement: Literal['unaware','indifferent','mild','engaged','mobilized']
    stance_source: Literal['gut','deliberate']
```

Actual impact is stored separately by the world model (`ledger_impacts` per agent, per policy) so the perception gap can be computed.

### 8.4 Update rules (defaults in Appendix C)

- **Gut updates (System 1 habit):** `stance += clip(valence × 0.5, ±0.5)`, `certainty ≤ 0.3`, `stance_source='gut'`. Never touches slow tier.
- **Deliberate updates (System 2):** `stance_delta ∈ {-2..+2}` per sweep, certainty and salience set from output, `stance_source='deliberate'`.
- **Engagement:** recomputed from |stance|, salience and actions taken, then clamped to move at most one level per sweep. Thresholds: unaware if not aware; indifferent if |stance| < 0.6 or salience < 0.2; mild < 1.6; engaged < 2.4; else mobilized; and cannot exceed the level allowed by `civic_baseline` (≥ 0.7 for mobilized, ≥ 0.4 for engaged).
- **Slow changes:** a reflection may propose `{attribute, direction, evidence_refs}`. The engine appends to `pending_evidence`; a change applies only when ≥ 3 consistent evidence items exist (≥ 2 if from trusted sources with trust ≥ 0.7), raised by 1 if openness < 0.35 or the attribute is identity-relevant. Step size: 1 scale point (attitudes) or 0.1 (trust, identity); cap one change per attribute per 4 sweeps.
- **Decay:** mood moves 50% of the way to baseline each sweep without new triggers; concern salience × 0.6 per sweep without reinforcement; concerns below 0.05 drop.
- **Life events** apply only as engine state transitions; LLM outputs that assert life changes are discarded and logged as `invalid_claim`.



### 8.5 Rendering for prompts

- **Persona card** (fixed tier → narrative, ~300–600 tokens full tier, ~150 standard tier), cached per agent.
- **State summary** (slow + fast + relevant policy stances), ~150 tokens.
- **Perception view** (§13.7), ~150 tokens.
- **Memories** (§9.2), 10–20 items.
- **Inputs** for this sweep.

Token budget for System 2 prompt: 3,500 tokens (configurable); truncation order: older memories → perception details → state detail. Anchors are never truncated.

---



## 9. Memory



### 9.1 Writes

Every input processed by System 1, every message sent or received, every resolved action outcome, every media item read, and every reflection becomes a memory row. Importance:

- ignore → 1–3 (System 1 arousal × 3, rounded, min 1)
- habit → 3–5
- escalated → scored by System 2 (`importance` field in output)
- reflections → 6–9 (from reflection output)

Embeddings are computed by the embedding role at write time (batched per sweep).

### 9.2 Retrieval

```
score = w_r × recency + w_i × importance/10 + w_s × cosine(query, embedding)
recency = 0.85 ^ (s - memory.sweep)
defaults: w_r = 1.0, w_i = 1.0, w_s = 1.0; k = 15 (full tier), 8 (standard tier)
query = concatenation of this sweep's escalated inputs
```

Anchors are always prepended. Retrieval is a pgvector HNSW query filtered by `(run lineage, agent_id, dropped_sweep IS NULL)` over the top 200 by similarity, then re-ranked in Python.

### 9.3 Compression and forgetting

At step 8, for each agent: memories with `importance ≤ 3` and age ≥ 4 sweeps and no reinforcement (no later memory on the same lineage/topic) get `dropped_sweep = s`. Memories older than 8 sweeps are grouped by 4-sweep window and summarized by one LLM call into a `summary` memory (importance = max of group); originals get `summarized_into`. Standard-tier agents keep at most 60 live memories (oldest low-importance first out).

---



## 10. System 1 (TypeSafe Jev / System One)



### 10.1 Client

System 1 is a **System One** decision model: `POST {base_url}` with `model`, `state`, and a map of typed `questions`; the response is `answers` keyed by the same ids. The live default is **hosted TypeSafe Jev** ([API reference](https://docs.typesafe.ai/api)):

```
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <TYPESAFE_API_KEY>
Content-Type: application/json
```

Request: `{ "model": "jev-latest", "state": "<agent + input>", "questions": { ... } }`.  
Answer types: **choice** (`choice`, `probabilities`, `confidence`), **noul** (`noul` in 0–1; mapped internally to yes/no), **score** (`score`, `legend`, `probabilities`, `confidence`).

The adapter (`sim/system1/openjev.py`, `kind: system_one`) is the only module that knows the wire format. Switching provider is a `models.yaml` change:

| Catalog name       | Endpoint                                      | Auth                         |
| ------------------ | --------------------------------------------- | ---------------------------- |
| `typesafe-hosted`  | `https://api.typesafe.ai/v1/systemone`        | `TYPESAFE_API_KEY` (or `TYPEFACE_API_KEY`) |
| `openjev-local`    | `http://localhost:3000/v1/systemone`          | optional `OPENJEV_TOKEN`     |
| `openjev-fixtures` | (no network)                                  | recorded / synthetic fixtures |
| `stub-system1`     | in-process deterministic stub                 | none                         |

Local OpenJev (optional): `openjev serve --backend mlx --model openjev/openjev-MLX-4bit --profile openjev` on Apple silicon, or vLLM + `openjev serve --backend vllm` on GPU. Keep OpenJev on `:3000`; the sim API uses `:8000`.

If the hosted key is missing, or a live call fails and `fallback_fixtures: true`, the adapter uses recorded fixtures under `tests/fixtures/openjev/` so engine tests still run.

```python
class System1Client(Protocol):
    def decide(self, state: str, questions: dict[str, QuestionSpec]) -> dict[str, Decision]: ...

class Decision(BaseModel):
    value: Any
    probs: dict[str, float]
    confidence: float
```

### 10.2 State string

```
Agent: {name}, {age}, {occupation}, {neighborhood}. Household: {household_short}.
Traits: openness {o}, neuroticism {n}. Stress: {stress_band}. Mood: {mood_band}. Attention left: {attention_band}.
Concerns: {top3_concerns}. Engagement on {policy}: {engagement}. Stance: {stance_band}.
Input ({kind}, from {source_label}, closeness {closeness_band}, seen before: {repeat_count}):
{input.content}
Impact on them: {impact_band}.
```



### 10.3 Question set `notice_route_v1`

Live System One calls use `notice_route_v1_openjev()` in `sim/system1/questions.py` (instructions + criteria). Stubs still use internal `{type, options[]}`; `to_openjev_questions()` converts them when needed. `notices` is a **noul** (P(yes)); the adapter maps `noul ≥ 0.5` → `yes`.


| Question     | Type   | Labels / criteria                                                |
| ------------ | ------ | ---------------------------------------------------------------- |
| notices      | noul   | true = they register the input; false = they overlook it         |
| valence      | choice | very negative, negative, neutral, positive, very positive        |
| arousal      | choice | low, medium, high                                                |
| route        | choice | ignore, habit, escalate                                          |
| habit_action | choice | none, grumble at home, mention to a coworker, pay and move on    |
| relevance    | choice | not me, someone close, me directly                               |




### 10.4 Routing

```
if notices.value == 'no' and notices.confidence >= 0.7: route = ignore
elif any(trigger(input, agent)): route = escalate         # escalated_by = trigger name
elif route.value == 'escalate': route = escalate
elif route.confidence < τ_conf (0.7): route = escalate    # escalated_by = 'low_confidence'
else: route = route.value
```

Triggers: `arousal == high`; `impact_magnitude ≥ 0.6`; close contact (closeness ≥ 0.7) asking (`intent == ask`); `repeat_count ≥ 2` on the same topic (third exposure); clash with held belief (|stance or attitude| ≥ 2 and valence opposite in sign).

Cap: at most `max_escalations_per_agent` (default 3) inputs per agent per sweep go to System 2; extras become habit.

### 10.5 Attention budget

`attention = attention_baseline × (1 − 0.5 × stress) × (1 − life_load)`, in units of inputs (default baseline 6). Each processed input costs 1; escalated inputs cost 2. Unprocessed inputs stay pending until expiry.

### 10.6 Habit templates

Per input kind, e.g. direct_impact: `pay and move on`, `grumble at home` (circle message to household, template text, no LLM), `mention to a coworker`, `check the account`. Habit actions write template messages through the bus (with `source='habit'`), which can still spread via circles (§12.3) at a reduced rate (× 0.5).

### 10.7 Other System 1 jobs

- `intent_router_v1`: routes a free-text intent to {mechanical, open_ended, social, entity_changing, institutional, talk, post, invalid}.
- `delta_scale_v1`: first-pass plausibility of a delta's magnitude for one week.
- `circle_reacts_v1`: does the circle react / does anyone pass it on (§12.3).



### 10.8 Tuning and audit

- Reference set: ≥ 2,000 persona × input pairs per question set, labeled by System 2 in character (Appendix A.5). Agreement target ≥ 80% on `route`, reported by subgroup.
- Each run samples 1% of System 1 decisions (min 50) for System 2 re-judgment; agreement < 70% in any subgroup raises a run warning.
- Calibration targets (§19.3) set `τ_conf` and trigger thresholds.

---



## 11. System 2 and other LLM roles (stubs or Ollama)



### 11.1 Client

Default catalog entries for System 2, circle, world master, institutions, narrative, reflection and judge are **`stub-llm`** (`sim/llm/stub.py`): deterministic JSON that still exercises schemas, routing and fallbacks. Point those roles at `llama3.2-3b` in `defaults.yaml` once Ollama is running (`ollama pull llama3.2:3b`).

Ollama path: `POST /api/chat` with `format` set to the role's JSON schema (structured outputs), `options` from config plus derived `seed`, `stream: false`. Validation: pydantic parse → semantic checks (§11.5) → on failure, one repair retry with the validation errors appended, then a second full retry at temperature × 0.5, then the call is marked invalid and the role's fallback applies. Embeddings use `nomic-embed-text` or `stub-embed`.


| Role         | Fallback on invalid output                                     |
| ------------ | -------------------------------------------------------------- |
| system2      | Treat as habit: highest-probability habit action from System 1 |
| circle       | No circle reaction; no spread                                  |
| world_master | Reject the action as "no effect"; delta not proposed           |
| institution  | No response this sweep                                         |
| reflection   | No slow changes; fast decay only                               |
| narrative    | Regenerate agent (population build)                            |




### 11.2 Roles and prompts


| Role                  | Called in step   | Per                           | Output schema |
| --------------------- | ---------------- | ----------------------------- | ------------- |
| system2               | 5                | escalated agent               | A.1           |
| circle                | 5                | conversation / share          | A.2           |
| world_master_resolve  | 6                | entity batch                  | A.3           |
| world_master_judgment | 1                | policy judgment hook × entity | A.3           |
| world_master_realize  | 2                | event                         | A.3           |
| institution           | 7                | triggered institution         | A.4           |
| reflection            | 8                | agent                         | A.6           |
| memory_summary        | 8                | agent window                  | text          |
| narrative             | population build | agent                         | A.7           |
| judge                 | checks           | sample                        | A.8           |


Prompt templates are versioned files (`sim/llm/prompts/<role>_v<n>.jinja`); the template version is part of the request and thus of the cache key.

### 11.3 Voice control

Persona card includes the `voice` block as explicit rules: max sentences per message, allowed register, tics with frequency, polish ceiling ("no word you wouldn't say to a coworker"), and 2–4 sample utterances. Messages failing a lightweight voice check (length > 2× voice max, banned-phrase list such as "it's not either-or", "multifaceted") trigger a repair retry.

### 11.4 Action menu (System 2 `actions[].type`)

`ignore`, `talk`, `post`, `seek_information`, `adapt_behavior`, `comply`, `evade`, `game`, `complain_formally`, `organize`, `join_group`, `leave_group`, `change_civic_intent`.

### 11.5 Semantic validation

- `talk.to` must be a contact key in the agent's roster; `post.group` a context the agent belongs to; `complain_formally.institution` an institution entity reachable by the agent.
- Escalation ladder: an action is allowed only if the agent's resulting engagement level permits it (talk: mild+; post: mild+; complain_formally: engaged+; organize: mobilized), and the agent's `civic_baseline` allows that rung.
- Capability rules (`sim/agents/capabilities.py`): age (no voting < 18), schedule (no daytime meeting during a day-shift week), resources (no purchase above available funds band), access (no group a minor can't join).
- Rate limit: messages per sweep ≤ `round(2 + 8 × extraversion × engagement_factor × (1 − life_load))`, max 10.
- Stance delta within ±2; salience and certainty in [0, 1].
- No claimed facts about other agents' private states; no new life events.

Invalid items are dropped individually (not the whole output) and logged.

---



## 12. Social world: circles, contexts, messages and exposures



### 12.1 Roster generation

At population build (§16.4), each agent gets a roster:


| Sphere      | Default count              | Generation                                                 |
| ----------- | -------------------------- | ---------------------------------------------------------- |
| household   | from household description | Named; not separate agents unless sampled                  |
| close       | 3–8                        | Named; family/friends from narrative                       |
| work_school | 1–3 aggregate contacts     | "Priya and four other ER nurses"; `context_id` = workplace |
| community   | 1–2 aggregate              | Neighbors; `match_filter` on tract + age band              |
| online      | per group membership       | One aggregate contact per group                            |


Counts and disagreement rates are calibrated to egocentric network data (GSS core discussion network items). `stance_tendency` is sampled so that the share of close contacts disagreeing with the agent on a salient issue matches the calibration target (default 0.3).

### 12.2 Inbound grounding

When the circle subagent voices a contact on topic *T* in sweep *s*:

1. If the contact has `context_id`: sample up to 5 agents from that context (excluding the agent), seeded; read their current policy stance on *T* and their last message on *T* if any.
2. Else if `match_filter`: sample up to 5 agents matching the filter.
3. Combine with `stance_tendency` into a short "what they think" brief passed to the circle prompt (mean stance band, spread, 1–2 recent paraphrased lines, labeled as views of "people like them").
4. If no matching agents exist (small contexts at low ratios), use `stance_tendency` alone and mark the reply `grounded=false`.



### 12.3 Outbound spread

When an agent shares content (talk, habit grumble, or post outside groups):

```
p_pass_on(context) = base_rate[sphere]                    # defaults: household 0.05, close 0.15, work_school 0.35, community 0.2
                   × landing_strength                      # circle output A.2 'landed' 0..1
                   × size_factor(context.real_size)        # min(1, log10(real_size)/3)
                   × amplification_draw                    # §15 chance amplification
n_recipients ~ Binomial(min(agents_in_context, cap=5), p_pass_on)
```

Recipients are sampled from the context's current members (seeded). Each gets an exposure with `deliver_sweep = s + 1`, `source_kind='circle_spread'`, `path` extended by `{circle_step: contact_key}`, and content re-voiced by the circle output's `passed_on_version` (distortion; §15 misperception may further alter it).

### 12.4 Group posts

For each post to group *g*: each member *m* sees it in s+1 with probability

```
p_see = feed_base(g) × (0.5 + 0.5 × closeness(m, poster)) × (1 + 0.1 × min(engagement, 20))
```

`closeness(m, poster)` = 0.2 default for co-members not in each other's circle. Engagement increases when members reply (System 2 `post` with `reply_to`). Posts are re-evaluated for visibility each sweep for two sweeps.

### 12.5 Media and institutions

Broadcast messages create exposures for every agent whose information diet includes the source, weighted by `trust(source)` and a per-agent consumption probability from the information diet (calibrated to Pew media data).

### 12.6 Conversations

`talk` with `channel in (call, in_person)` to a named contact runs a conversation: alternating calls — circle subagent voices the contact (A.2 `reply`), agent's System 2 continuation voices the agent (A.1 subset) — up to 4 turns total; stops early if either side's output sets `end: true`. Contact memory for that contact is updated in step 8 with a one-line summary.

### 12.7 Traceability

`exposures.path` is an ordered list of hops: `{agent}`, `{context}`, `{circle_step}`, `{media}`, `{institution}`. `messages.lineage` points to the root. Cascade queries walk lineage + path and are materialized per run in step 9 for the top 20 cascades by reach.

---



## 13. World model: canon, rules engine, world master, resolver



### 13.1 Entity kinds (abridged)


| Kind                 | Required fields                                                     |
| -------------------- | ------------------------------------------------------------------- |
| institution          | jurisdiction, functions[], thresholds{}, voice, contact_channels[]  |
| school               | grades, enrollment, attendance_zone (geom), rules{}, enforcement{}  |
| workplace / business | sector, employees_real, hours, shifts[], location, customers_weekly |
| zone                 | geom, rules{}                                                       |
| route                | geom, modes[], travel_time_by_mode{}                                |
| group                | platform, members_real, activity, norms                             |
| media                | outlet_type, audience_real, slant, publishing_schedule              |


Each entity also has `description` (free text) and `sources[]`; `invented=true` flags builder-invented details.

### 13.2 Policy package spec

```yaml
id: phone_ban_6_12
version: 3
jurisdiction: maplewood_usd
announce_sweep: 0
effective_sweep: 1
rules:
  - id: all_day_ban
    applies_to: { entity_kind: school, grades: [6,7,8,9,10,11,12] }
    effect: { set_field: rules.phones, value: "locked_pouch_all_day" }
exemptions: []
mechanics:                       # rules-engine hooks (Python functions by name)
  - per_agent: phone_ban.daily_impact      # creates direct_impact inputs for students and parents
judgment_hooks:                  # world-master calls, step 1
  - id: enforcement_strictness
    per: school
    sweeps: every
    question: "How strictly is the ban enforced this week, and by which teachers?"
    output_field: enforcement.strictness   # 0..1 + description
announcements:
  - sweep: 0
    via: [institution:maplewood_usd, media:maplewood_ledger]
    text: "Maplewood Unified announces an all-day phone ban for grades 6–12, starting next week."
open_mode_limits:                # what institutions may change in open mode
  allowed_amendments: [add_exemption, add_contact_channel, change_enforcement]
outcome_parameters:              # researcher-set, never decided by the world master
  learning_effect: none          # none | small | moderate
```

`outcome_parameters` hold contested real-world effects (e.g. learning outcomes). The world master receives them as facts and may not contradict them; sensitivity runs vary them across ensembles.

### 13.3 Rules engine

Pure functions registered by name: `(canon_view, agent, sweep, rng) -> list[Input | Delta | LedgerEntry]`. No LLM. Unit-tested in isolation. Handles: charges, schedule changes, travel times, counts, thresholds, capacity.

### 13.4 World master

Called with: canon excerpt for the relevant entities (fields + description), policy package (rules + outcome parameters), the requests or hooks, persona summaries of requesting agents (for open-ended actions), and a seeded random draw per request expressed as a percentile ("chance roll: 62nd percentile") so outcomes vary across seeds without the LLM generating randomness. Output A.3.

### 13.5 Delta commit checks


| Check         | Implementation                                                                                                                     | On fail                                  |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Schema        | pydantic per entity kind                                                                                                           | reject                                   |
| Contradiction | rule set per kind (retired entity can't change; capacity ≥ 0; hours valid) + System 1 `delta_contradiction_v1` against description | return to world master once, then reject |
| Scale         | per-field max weekly change (config) or System 1 `delta_scale_v1`; exceeding needs a cited shock                                   | reject                                   |
| Cause         | cause list non-empty and each cause resolvable                                                                                     | reject                                   |
| Version       | applied as new `world_entities` row at sweep s                                                                                     | —                                        |




### 13.6 Resolver and collisions

1. Router (System 1 `intent_router_v1` or explicit `type`) assigns each intent a resolver.
2. Open-ended intents are grouped by target entity. Each group is resolved in one world-master call that sees all requests (in seeded order) and the entity's capacity, so outcomes respect capacity ("ten nurses ask for day shifts; three granted").
3. Outcomes write `actions.outcome`, a memory for the agent (`type='action'`, importance from outcome magnitude), and deltas.



### 13.7 Perception view

Built per agent from canon entities in the footprint (home zone, routes, workplace, school(s), groups, frequented businesses) plus the agent's own ledger impacts; rendered as short facts and one-line descriptions. Values are taken as of the last sweep the agent "observed" the entity (direct contact or an exposure about it), so views can be stale.

---



## 14. Institutions and media



### 14.1 Institution agents

Each institution/media entity has an institution agent with: voice, mandate, thresholds, inbox (formal messages), watch list (aggregates, groups, media), and a response history.

### 14.2 Thresholds in real-population terms

```
weighted_count = Σ agent.weight over qualifying agents/messages this sweep (or rolling window)
trigger if weighted_count ≥ threshold_real
```

Examples (defaults, per institution config): school board formal complaints ≥ 100 residents in 2 sweeps; group size ≥ 500 residents; post engagement ≥ 50 residents; meeting turnout ≥ 150. Media agents trigger on: post visibility ≥ 300 residents, institutional statements, events with magnitude ≥ 0.6, plus a weekly baseline story chance.

### 14.3 Response

Institution LLM (A.4) chooses: no response, statement (with framing), enforcement change, amendment (open mode only, within `open_mode_limits`), or story (media). Outputs create broadcast messages → exposures in s+1, deltas, or policy amendments effective s+1. Amendments in open mode are recorded in `policy_packages` as a new version linked to the run.

---



## 15. Randomness engine


| Channel              | Mechanism                                                                                                                                                       | Defaults                                                                          |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Life events          | Per agent per sweep, Bernoulli per event type with weekly rates from demographic base-rate tables (`randomness/base_rates.csv`)                                 | Job loss, new job, illness, car breakdown, birth, move, family conflict, windfall |
| Shocks               | Shock library entries with weekly probability × chaos_level, or scripted                                                                                        | Storm, utility outage, price spike, employer layoffs, unrelated scandal           |
| Ambient              | 1–3 ambient developments per sweep per place, realized by world master                                                                                          | Pothole, new business, rumor                                                      |
| Chance amplification | Per post/story: with p = 0.02 × chaos_level, visibility × 5 or media pickup                                                                                     | —                                                                                 |
| Misperception        | Per exposure read: p = 0.05 (calibrate to policy-knowledge surveys) that content is replaced by a distorted variant (System 2 or template) and `distorted=true` | —                                                                                 |
| Behavioral noise     | LLM temperature; ±10% jitter on attention baseline and visibility per sweep                                                                                     | —                                                                                 |


All draws use §6.1 seeds per channel. `chaos_level` multiplies shock and amplification probabilities.

---



## 16. Population generation



### 16.1 Inputs

City pack (approved), sampling ratio *r*, generator config, seed. Target agent count `N = round(pop / r)`.

### 16.2 Skeleton

1. Load ACS PUMS persons + households for PUMAs intersecting the place; restrict and reweight to the place using tract-level ACS margins (iterative proportional fitting on age × sex × race/eth × education × household type per tract).
2. Sample N individuals with probability ∝ adjusted weight, with tail oversampling (§16.3). Each sampled person keeps a household description (members' ages/relationships) from their PUMS household.
3. Assign home tract (from IPF allocation) and home point (random within residential parcels/buildings from OSM, seeded).
4. Assign workplace via LEHD origin–destination by home block group and the worker's industry; school by attendance zone and grade.



### 16.3 Variation and tails

- **Fusion (statistical matching):** for each attitude survey (GSS, ANES/CES, Pew), find k = 5–10 nearest donors on shared variables (age band, sex, race/eth, education, income band, region, party where available; Gower distance) and draw each attribute block from a randomly chosen donor in the pool.
- **Copula jitter:** continuous scales transformed to normal scores, jittered with σ = 0.15 under a Gaussian copula fitted on donor data, back-transformed; preserves correlations.
- **Oversampling:** groups listed in config × 2–3 (rural, 80+, recent immigrants, people with disabilities, low-propensity voters, strong minority views); weights divided accordingly.
- **Synthetic tails:** 2–5% generated by combining donors from different cells under plausibility constraints; `is_synthetic_tail=true`, weight × 0.25.
- **Local attitude adjustment:** apply MRP place-level offsets (§17.2) to attitude priors.
- **Weights:** final weights calibrated (raking) to place population totals.



### 16.4 Narrative and roster (LLM)

Narrative role (A.7) receives the structured record and writes biography, formative experiences, voice block, quirks, contradictions, anchors and roster seeds. Consistency checks (rule-based: ages/durations/household; plus judge sample) reject contradicting outputs; up to 3 regenerations, then the agent is resampled.

### 16.5 Tiers and promotion

Full-tier agents chosen at random (stratified by segment) at `full_tier_share`. Promotion when engagement reaches `engaged`: narrative expanded by the narrative role (constrained by history and existing narrative), memory cap lifted, and `agent_state.tier='full'` recorded at that sweep.

### 16.6 Burn-in

4–8 sweeps with no policy (configurable), full engine, seed = population seed. Burn-in memories and state become the baseline; experiment runs start from `baseline_sweep` and read burn-in rows via a population-level baseline run in the lineage.

### 16.7 Checks (blocking freeze)


| Check                  | Method                                                                                                              | Default pass condition                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Demographics           | weighted marginals and key joints vs ACS                                                                            | each cell within ±3 pp (marginals), total variation distance ≤ 0.08 (joints)           |
| Attitude fidelity      | held-out GSS/ANES items answered by agents (System 2 in character, A.1 survey mode) vs real respondents by subgroup | per item JS divergence ≤ 0.1 overall, ≤ 0.2 by subgroup; SD ratio (agents/real) ≥ 0.75 |
| Persona consistency    | 5 anchor questions per agent                                                                                        | ≥ 95% agents fully consistent                                                          |
| Narrative plausibility | judge on 5% sample + human review of 20                                                                             | 0 contradictions in human sample; judge flag rate ≤ 3%                                 |
| Stereotype audit       | tropes classifier/judge across groups                                                                               | no group with flagged-trope rate > 2× overall                                          |


Thresholds are starting values; results are stored in `populations.checks` and shown in the population viewer.

---



## 17. Place import (city packs)



### 17.1 Pipeline jobs


| Step | Job           | Main sources                                                                          | Output                                       |
| ---- | ------------- | ------------------------------------------------------------------------------------- | -------------------------------------------- |
| 1    | resolve_place | Census TIGER/Line places, counties, school districts; city GIS                        | boundary, jurisdictions (user confirms)      |
| 2    | demographics  | ACS PUMS (IPUMS), ACS tract tables                                                    | tract margins, PUMA set                      |
| 3    | commutes      | LEHD LODES                                                                            | OD matrices by block group and industry      |
| 4    | institutions  | OSM (Overpass extract), NCES CCD, GTFS, CMS hospital data, IRS EO BMF, city open data | canon entities                               |
| 5    | texture       | Web research agent over local news, council agendas, neighborhood pages, 311 data     | cited theme summaries                        |
| 6    | attitudes     | MRP over national surveys; precinct ballot results; local polls                       | place-level and tract-level attitude offsets |
| 7    | canon         | World builder                                                                         | world_entities baseline                      |
| 8    | citizens      | Population generation (§16)                                                           | population (after approval and ratio choice) |
| 9    | report        | —                                                                                     | import report                                |


Each job writes its outputs with `sources[]` and `as_of`. Jobs are idempotent and resumable.

### 17.2 MRP

Multilevel logistic/ordinal models per attitude item with predictors age × sex × race/eth × education × income band × party (where available) and random effects for state and region; poststratify to place tract cells from ACS. Calibrate with precinct-level ballot measure results (logit shift so predicted yes-share matches observed per relevant measure). Output: per-cell attitude offsets with standard errors; cells with SE above threshold are flagged in the report.

### 17.3 Import report

Per layer: coverage, confidence (high/medium/low by rule), as-of date, sources, gaps and flags, invented-detail count. Approval requires the user to acknowledge all low-confidence layers.

### 17.4 Rules for real places

- Real institutions may be named; real individuals are never entities or agents. Offices and roles only ("Council District 4 office", "a local reporter").
- Businesses anonymized by default (`display_name` generated, factual fields kept); opt-in per pack.
- Web research stores facts and short summaries with citations, never copied article text; respects robots/terms; social media used only for aggregate themes.
- Every source has `as_of`; backtests use anonymized place and policy names (§19.3).

---



## 18. API and environment interface



### 18.1 REST (FastAPI), abridged


| Method | Path                                         | Purpose                                               |
| ------ | -------------------------------------------- | ----------------------------------------------------- |
| POST   | /places/import                               | Start an import `{query}`                             |
| GET    | /places/{id}                                 | Pack, jurisdictions, report                           |
| POST   | /places/{id}/jurisdictions                   | Confirm/adjust jurisdictions                          |
| POST   | /places/{id}/approve                         | Approve pack                                          |
| POST   | /populations                                 | Build population `{place_id, sampling_ratio, config}` |
| GET    | /populations/{id}                            | Status, checks                                        |
| POST   | /policy-packages                             | Create/version a policy package                       |
| POST   | /estimate                                    | Run-time estimate (§7.5) for a proposed config        |
| POST   | /experiments                                 | Create experiment; enqueue runs per seed              |
| POST   | /runs/{id}/pause · /resume · /step · /cancel | Run control                                           |
| POST   | /runs/{id}/branch                            | `{fork_sweep, intervention}` → new run                |
| POST   | /runs/{id}/replay                            | Replay from cache                                     |
| GET    | /runs/{id}/sweeps/{s}/map                    | Agent points + colors (stance/engagement) for the map |
| GET    | /runs/{id}/sweeps/{s}/metrics                | Metrics by segment                                    |
| GET    | /runs/{id}/sweeps/{s}/feed                   | Events, institution actions, top cascades             |
| GET    | /runs/{id}/agents/{aid}?sweep=               | Profile, state, circle, memories, actions             |
| GET    | /runs/{id}/agents/{aid}/why?sweep=           | Why-chain (§18.4)                                     |
| GET    | /runs/{id}/cascades                          | Top cascades with paths                               |
| POST   | /runs/{id}/probes                            | Interview/focus group/survey (§18.3)                  |
| GET    | /experiments/{id}/ensemble                   | Ensemble outcome distributions and branch comparisons |


WebSocket `/ws/runs/{id}`: pushes `sweep_done`, `phase_progress {phase, done, total}`, `warning`, `status`. Backed by Postgres `LISTEN/NOTIFY`.

### 18.2 Screens

Live run view, agent inspector, run setup and place import follow the prototype. Also: world builder, population viewer, policy editor, cascade explorer, research studio, experiment manager. Map: MapLibre base map + deck.gl ScatterplotLayer for agents (positions jittered within 30 m for privacy of the visualization only), PolygonLayer for districts/zones, IconLayer for institutions. Cascade explorer: Sigma.js over contexts and agents along cascade paths.

### 18.3 Probes


| Mode                   | Behavior                                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| out_of_world (default) | Agent answers from a read-only snapshot of its state and memories at sweep s; nothing written to run tables; stored in `probes`      |
| in_world               | Scheduled as an event at sweep s+1 (e.g. "a poll call", "town hall"); creates inputs and memories; affects the run (use on a branch) |


Interview: free-text questions → System 2 `interview` prompt (A.1 interview mode) with persona card, state, memories and the instruction to answer only from what the agent knows by sweep s. Focus group: recruit 6–8 agents by filter; moderator (researcher or moderator LLM role) asks questions; each agent answers in its own call with the transcript so far; private stance recorded before the session; extraversion governs turn-taking probability. Survey: open-ended questions to N agents, answers coded into themes by a coding role.

### 18.4 Why-chain

Assembled from stored rows only (no new LLM call): triggering inputs → System 1 decision (answers + escalated_by) → retrieved memory ids → System 2 interpretation, reasoning and actions → outcomes and state updates.

---



## 19. Testing, validation and observability



### 19.1 Tests


| Level       | Scope                   | Examples                                                                                                                                                                 |
| ----------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Unit        | Pure functions          | seed derivation, update rules, engagement clamps, thresholds, rules-engine mechanics, delta checks, visibility formula                                                   |
| Contract    | Model adapters          | System One adapter against recorded fixtures and live TypeSafe; Ollama schema validation and repair loop                                                                 |
| Integration | Engine with stub models | 20-agent world, deterministic stub System 1/System 2; asserts message delivery timing, no intra-sweep leakage, collisions respect capacity, branch lineage reads         |
| Golden      | Replay                  | Recorded MVP run replays byte-identical metrics from cache                                                                                                               |
| Fidelity    | Population checks       | §16.7 on each built population                                                                                                                                           |
| Behavioral  | Scenario sanity         | phone-ban MVP: students' mean stance < 0 by sweep 1; awareness among non-parents < 60% at sweep 4 absent media; parents' engagement rises after an early-dismissal shock |




### 19.2 Persona drift checks

Every 4 sweeps, each full-tier agent and a 10% sample of standard agents answer 5 anchor questions via System 2 (A.1 survey mode). Mismatch → `drift_flag` in agent_state; > 2% flagged agents in a run raises a warning; flagged agents get their persona card re-emphasized (anchors moved to top, voice rules repeated) for the rest of the run.

### 19.3 Calibration and validation

- **Base rates:** notice/care shares (issue-salience polls, "don't know" rates), starting attitudes and trust (GSS, Pew), circle size and disagreement (GSS network items), media consumption (Pew), life-event rates (BLS, CDC, Census), opinion variance (panel surveys).
- **Backtests:** anonymized past policies with known reaction arcs (candidates in §20). Pass = the arc's direction and timing of main turning points emerge in ≥ 60% of ensemble runs without being prompted.
- **Ablations:** switch off circle spread, media agents, randomness, institutions in turn; report which outcomes disappear.
- **Variance checks:** stance SD by segment vs real data; flag if ratio < 0.75.
- **Hindsight checks:** compare runs with neutral vs real policy names; large differences flag leakage.
- **Human comparison:** small real focus groups on the same stimuli; compare theme sets.



### 19.4 Metrics (per sweep, weighted)

Awareness %, stance distribution (mean, SD, % ≥ +1.2, % ≤ −1.2) by segment, engagement-ladder counts (in real-population terms), message volume and sentiment by context kind, compliance/evasion counts, perception gap (perceived vs actual impact by segment), System 1 escalation rate, System 2 validity rate, drift flags. Stored in `metrics(run_id, sweep, segment, name, value)`.

### 19.5 Observability

Structured logs (JSON) with run_id/sweep/phase/agent_id; per-phase durations and per-role latency histograms from `model_calls`; run warnings table surfaced in the UI (validity rate < 95%, drift > 2%, System 1 agreement < 70%, cache misses on replay).

### 19.6 Guardrails

- Outputs labeled as scenarios in every export and screen.
- Subgroup audit attached to every ensemble report.
- No real individuals; anonymized businesses by default.
- Minors (age < 18): content filter on all generated text for and by minor agents; no romantic/sexual content; school-appropriate language; violations replaced with a neutral template and logged.

---



## 20. Open questions

1. Is one week fine-grained enough for fast dynamics (a post going viral in a day, school-week evasion), or do some contexts need daily sub-steps inside a sweep?
2. How much autonomy should government agents have to amend policy in open mode?
3. Which historical policy is the first backtest (e.g. an anonymized congestion charge or an earlier school phone policy)?
4. Target hardware for benchmarks, exact local model ids, and which role moves to a larger model first (likely the world master).
5. Should probes default to out-of-world in all studies, or should some studies use in-world polls by design?
6. Which surveys can be licensed for this use, and which attitude items are held out for fidelity checks?
7. ~~Exact request/response format of the chosen OpenJev implementation (adapter only).~~ **Resolved (v0.2):** hosted TypeSafe `POST /v1/systemone` with `jev-latest`; adapter in `sim/system1/openjev.py`. Local OpenJev remains optional.

---



## 21. Milestones and acceptance criteria



### Phase 1 — MVP

Scope: one composite town (~20,000 residents) at 1:100 (~200 agents); world brief instead of full import (steps 2–4 of §17 only for demographics if available); contexts: households (in circles), workplaces, schools (parent and student channels), one online group, one local news agent, school board institution; one policy (school phone ban); 12 sweeps; 5 seeds; closed mode; hosted TypeSafe Jev for System 1 and stub (or Ollama) LLMs; minimal UI (live run view, agent inspector, run setup).


| #   | Deliverable                                                           | Acceptance                                                                                                                                |
| --- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | Schema + migrations, seeding, cache, job queue                        | Unit tests pass; replay of a stub run is identical                                                                                        |
| M2  | Population generator (skeleton, fusion, narratives, rosters, burn-in) | §16.7 checks run and are reported; persona consistency ≥ 95%                                                                              |
| M3  | Engine steps 1–9 with stub models                                     | Integration tests pass                                                                                                                    |
| M4  | TypeSafe/OpenJev + Ollama adapters, prompts, validation               | Live System One call succeeds with `TYPESAFE_API_KEY`; System 2 validity ≥ 95% after repair; System 1 route agreement ≥ 80% on reference set |
| M5  | World master, resolver, deltas, institution + media                   | Collision test passes; all committed deltas have causes                                                                                   |
| M6  | Minimal UI + API + WebSocket                                          | Prototype screens work against real run data                                                                                              |
| M7  | MVP run                                                               | 5 seeds × 12 sweeps complete; human reviewer rates ≥ 80% of sampled agent weeks plausible; drift flags ≤ 2%; behavioral sanity tests pass |




### Phase 2 — Full mechanics

Place import (§17) end to end; user-chosen sampling ratio with estimator; all context types; shock library; ensembles of 30; probes (interview, focus group, survey); cascade explorer; population viewer; policy editor.

### Phase 3 — Validation and scale

Backtests and ablations; branching UI and experiment manager; open mode; larger places at higher ratios with fidelity tiers; model role upgrades; Parquet export and ensemble analysis.

---



## Appendix A. JSON schemas for model outputs

Schemas are passed to Ollama as `format`. Abridged below (full schemas in `sim/llm/schemas/`).

### A.1 System 2 appraise-and-decide (`system2_v1`)

```json
{
  "type": "object",
  "required": ["interpretation", "emotion", "importance", "policy_stance_update", "actions", "reasoning"],
  "properties": {
    "interpretation": {"type": "string", "maxLength": 300},
    "emotion": {"type": "object", "required": ["label", "intensity"],
      "properties": {"label": {"type": "string"}, "intensity": {"type": "number", "minimum": 0, "maximum": 1}}},
    "importance": {"type": "integer", "minimum": 1, "maximum": 10},
    "policy_stance_update": {"type": "object",
      "properties": {
        "policy_id": {"type": "string"},
        "aware": {"type": "boolean"},
        "stance_delta": {"type": "integer", "minimum": -2, "maximum": 2},
        "certainty": {"type": "number", "minimum": 0, "maximum": 1},
        "salience": {"type": "number", "minimum": 0, "maximum": 1},
        "perceived_policy": {"type": "string"},
        "perceived_personal_impact": {"type": "string"},
        "perceived_risks": {"type": "array", "items": {"type": "string"}},
        "perceived_benefits": {"type": "array", "items": {"type": "string"}}}},
    "actions": {"type": "array", "maxItems": 4, "items": {"type": "object",
      "required": ["type"],
      "properties": {
        "type": {"enum": ["ignore","talk","post","seek_information","adapt_behavior","comply","evade","game",
                          "complain_formally","organize","join_group","leave_group","change_civic_intent"]},
        "to": {"type": "string"}, "group": {"type": "string"}, "institution": {"type": "string"},
        "channel": {"enum": ["in_person","call","text","group_post","formal"]},
        "content": {"type": "string", "maxLength": 400},
        "intent_text": {"type": "string", "maxLength": 200},
        "intent": {"enum": ["inform","vent","ask","persuade","joke","organize","reply"]},
        "reply_to": {"type": "string"}}}},
    "reasoning": {"type": "string", "maxLength": 300}
  }
}
```

Modes: `survey` (single `answer` field constrained to the item's options + `reasoning`), `interview` (`answer` text in voice + `reasoning`), `continue_conversation` (`content`, `end`).

### A.2 Circle subagent (`circle_v1`)

```json
{
  "type": "object",
  "required": ["reactions", "landed", "pass_on"],
  "properties": {
    "reactions": {"type": "array", "items": {"type": "object",
      "properties": {"contact_key": {"type": "string"}, "reply": {"type": "string", "maxLength": 300},
                     "stance_expressed": {"type": "integer", "minimum": -3, "maximum": 3}}}},
    "landed": {"type": "number", "minimum": 0, "maximum": 1},
    "pass_on": {"type": "array", "items": {"type": "object",
      "properties": {"contact_key": {"type": "string"},
                     "passed_on_version": {"type": "string", "maxLength": 300}}}},
    "end": {"type": "boolean"}
  }
}
```



### A.3 World master (`world_master_v1`)

```json
{
  "type": "object",
  "required": ["outcomes", "deltas"],
  "properties": {
    "outcomes": {"type": "array", "items": {"type": "object",
      "properties": {"action_id": {"type": "string"},
                     "status": {"enum": ["granted","refused","partial","done","no_effect"]},
                     "detail": {"type": "string", "maxLength": 300},
                     "agent_experience": {"type": "string", "maxLength": 200}}}},
    "deltas": {"type": "array", "items": {"type": "object",
      "required": ["entity", "change", "cause"],
      "properties": {"entity": {"type": "string"}, "change": {"type": "object"},
                     "description_update": {"type": "string"},
                     "cause": {"type": "array", "items": {"type": "string"}},
                     "confidence": {"type": "number"}}}},
    "event_realization": {"type": "string"}
  }
}
```



### A.4 Institution (`institution_v1`)

```json
{
  "type": "object",
  "required": ["response"],
  "properties": {
    "response": {"enum": ["none","statement","enforcement_change","amendment","story"]},
    "headline": {"type": "string", "maxLength": 120},
    "text": {"type": "string", "maxLength": 800},
    "framing": {"type": "string", "maxLength": 120},
    "amendment": {"type": "object"},
    "enforcement_change": {"type": "object"},
    "reasoning": {"type": "string", "maxLength": 300}
  }
}
```



### A.5 System 1 reference labels (`s1_reference_v1`)

Same fields as §10.3 question set, answered by System 2 in character, plus `rationale`.

### A.6 Reflection (`reflection_v1`)

```json
{
  "type": "object",
  "required": ["reflections", "slow_proposals"],
  "properties": {
    "reflections": {"type": "array", "maxItems": 3, "items": {"type": "object",
      "properties": {"content": {"type": "string", "maxLength": 200},
                     "importance": {"type": "integer", "minimum": 6, "maximum": 9}}}},
    "slow_proposals": {"type": "array", "items": {"type": "object",
      "properties": {"attribute": {"type": "string"},
                     "direction": {"enum": ["up","down"]},
                     "evidence_refs": {"type": "array", "items": {"type": "string"}}}}},
    "self_narrative_line": {"type": "string", "maxLength": 160}
  }
}
```



### A.7 Narrative (`narrative_v1`)

Fields: `biography`, `formative_experiences[]`, `voice{fluency, tics[], answer_length, polish_ceiling, samples[]}`, `quirks[]`, `contradictions[]`, `anchors[]`, `roster_seeds[{label, sphere, description, stance_tendency}]`.

### A.8 Judge (`judge_v1`)

Fields: `contradictions[]`, `caricature_flags[]`, `voice_ok`, `score 1–5`, `notes`.

---



## Appendix B. Prompt templates (abridged)



### B.1 System 2 (`system2_v1.jinja`)

```
You are {{ name }}. Stay fully in character. You are not an assistant.

WHO YOU ARE
{{ persona_card }}

HOW YOU TALK
{{ voice_rules }}
Examples of how you sound:
{% for s in voice_samples %}- "{{ s }}"
{% endfor %}

FACTS THAT NEVER CHANGE
{% for a in anchors %}- {{ a }}
{% endfor %}

WHERE YOU ARE NOW (week {{ sweep }})
{{ state_summary }}
{{ perception_view }}

WHAT YOU REMEMBER
{% for m in memories %}- (week {{ m.sweep }}) {{ m.content }}
{% endfor %}

WHAT HAPPENED THIS WEEK
{% for i in inputs %}- {{ i.content }} [from {{ i.source_label }}]
{% endfor %}

People you can talk to: {{ roster_keys }}
Groups you're in: {{ groups }}
Things you could do: {{ allowed_actions }}

Decide how you see this and what, if anything, you do this week. Most weeks people do little.
You may be wrong about facts. Don't know things you couldn't know.
Answer only with JSON matching the schema.
```



### B.2 Circle (`circle_v1.jinja`)

```
You voice the people in {{ name }}'s life. Each person speaks for themselves, in short, natural lines.
They are not all on {{ name }}'s side.

{{ name }} just said/shared: "{{ shared_content }}" ({{ channel }})

People present:
{% for c in contacts %}- {{ c.key }}: {{ c.label }}. {{ c.description }}. Usually: {{ c.stance_tendency }}.
  What people like them are saying lately: {{ c.grounding_brief }}
  What {{ name }} and they talked about before: {{ c.contact_memory }}
{% endfor %}

Write each person's reaction, how strongly this landed with them (0–1), and who, if anyone,
would pass it on to others, in the words they'd use. Answer only with JSON.
```



### B.3 World master (`world_master_v1.jinja`)

```
You run the world of {{ place_name }} like a fair game master. You do not take sides.

Facts you must respect:
{{ canon_excerpt }}
Policy rules: {{ policy_rules }}
Fixed outcome assumptions (do not contradict): {{ outcome_parameters }}

Requests this week (resolve together; respect capacity):
{% for r in requests %}- [{{ r.action_id }}] {{ r.agent_summary }} wants to: "{{ r.intent_text }}". Chance roll: {{ r.percentile }}th percentile.
{% endfor %}

Decide each outcome and any changes to the world. Every change needs a cause.
Keep changes plausible for one week. Answer only with JSON.
```

---



## Appendix C. Default parameters


| Key                               | Default                                                     | Section |
| --------------------------------- | ----------------------------------------------------------- | ------- |
| engine.horizon_sweeps             | 12                                                          | 4       |
| engine.burn_in_sweeps             | 6                                                           | 16.6    |
| models.system1                    | typesafe-hosted (`jev-latest`)                              | 10.1    |
| models.system2 (and other LLM)    | stub-llm (swap to llama3.2-3b)                              | 11.1    |
| models.embeddings                 | stub-embed (swap to nomic-embed-text)                       | 11.1    |
| compute.workers                   | 2                                                           | 2       |
| system1.conf_threshold            | 0.7                                                         | 10.4    |
| system1.max_escalations_per_agent | 3                                                           | 10.4    |
| system1.attention_baseline        | 6 inputs                                                    | 10.5    |
| system1.audit_share               | 0.01 (min 50)                                               | 10.8    |
| update.gut_step_max               | 0.5                                                         | 8.4     |
| update.gut_certainty_max          | 0.3                                                         | 8.4     |
| update.slow_evidence_min          | 3 (2 trusted)                                               | 8.4     |
| update.slow_cooldown_sweeps       | 4                                                           | 8.4     |
| decay.mood_to_baseline            | 0.5 per sweep                                               | 8.4     |
| decay.concern_salience            | × 0.6 per sweep                                             | 8.4     |
| memory.k_full / k_standard        | 15 / 8                                                      | 9.2     |
| memory.recency_base               | 0.85                                                        | 9.2     |
| memory.drop_importance_max / age  | 3 / 4 sweeps                                                | 9.3     |
| memory.summarize_after            | 8 sweeps                                                    | 9.3     |
| memory.standard_cap               | 60                                                          | 9.3     |
| llm.system2_prompt_tokens         | 3,500                                                       | 8.5     |
| llm.max_retries                   | 2                                                           | 11.1    |
| messages.max_per_sweep            | 10                                                          | 11.5    |
| messages.expiry_sweeps            | 2                                                           | 5.3     |
| circle.close_contacts             | 3–8                                                         | 12.1    |
| circle.disagree_share             | 0.3                                                         | 12.1    |
| circle.pass_on_base               | household 0.05, close 0.15, work_school 0.35, community 0.2 | 12.3    |
| circle.max_recipients_per_share   | 5                                                           | 12.3    |
| circle.habit_spread_factor        | 0.5                                                         | 10.6    |
| conversation.max_turns            | 4                                                           | 12.6    |
| reflection.cycle_sweeps           | 4                                                           | 7.3     |
| population.donor_pool             | 5–10                                                        | 16.3    |
| population.copula_sigma           | 0.15                                                        | 16.3    |
| population.oversample             | 2–3× listed groups                                          | 16.3    |
| population.synthetic_tail_share   | 0.02–0.05                                                   | 16.3    |
| population.full_tier_share        | 0.05                                                        | 16.5    |
| randomness.amplification_p        | 0.02 × chaos                                                | 15      |
| randomness.misperception_p        | 0.05                                                        | 15      |
| randomness.noise_jitter           | ±10%                                                        | 15      |
| ensemble.default_seeds            | 30 (MVP: 5)                                                 | 4       |
| drift.check_every                 | 4 sweeps                                                    | 19.2    |
| drift.warn_share                  | 0.02                                                        | 19.2    |
| estimate.t_llm / t_s1             | 3 s / 0.3 s                                                 | 7.5     |


All defaults are starting values to be calibrated (§19.3).