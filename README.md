# ClinicalTrials.gov Query-to-Visualization Agent

Ask a question about clinical trials in plain English and get back a chart where **every number
links to the trials behind it**. A language model plans the analysis, and ordinary code fetches
the data from [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) and does all of the
counting. The model never writes a number.

- **Backend:** Python, FastAPI, Pydantic, async SQLAlchemy, Postgres
- **Frontend:** React, TypeScript, Vite, Tailwind, TanStack Query, Chart.js
- **Runs in:** Docker Compose, published at `https://ctviz.rayyanhuda.com` through a Cloudflare Tunnel

---

## Architecture

### The pieces

```mermaid
flowchart LR
    user["<b>Browser</b><br/>React app<br/>(React Router, TanStack Query,<br/>Chart.js)"]:::browser
    cf["<b>Cloudflare</b><br/>ctviz.rayyanhuda.com<br/>DNS + HTTPS"]:::cloud

    subgraph mac["Docker Compose, running on my Mac"]
        direction LR
        tunnel["<b>tunnel</b> (cloudflared)<br/>dials OUT to Cloudflare,<br/>so no ports are opened"]:::cloud

        subgraph appbox["<b>app</b>: FastAPI + uvicorn, port 8000"]
            direction TB
            site["React build<br/>served at / and /assets"]:::code
            api["API layer<br/>routes, saved charts,<br/>rate limit, errors"]:::code
            planner["<b>Planner</b> (app/agent)<br/>asks Claude, runs 3 probe tools,<br/>validates the plan"]:::llm
            executor["<b>Executor</b><br/>fetch, aggregate,<br/>build the chart, cite"]:::code
            client["ClinicalTrials.gov client<br/>retries, paging, cache"]:::code
            api --> planner
            api --> executor
            planner --> client
            executor --> client
        end

        db[("<b>db</b>: Postgres 16<br/>table saved_charts<br/>volume pgdata")]:::store
        cache[("cache volume<br/>JSON files, 24h")]:::store
    end

    claude["<b>Anthropic API</b><br/>the planner model"]:::llm
    ctgov["<b>ClinicalTrials.gov</b><br/>API v2"]:::ext

    user -->|HTTPS| cf
    cf <-->|tunnel| tunnel
    tunnel -->|"HTTP :8000"| api
    api -->|async SQL| db
    planner -->|"messages + tools"| claude
    client -->|"GET /studies"| ctgov
    client <--> cache

    classDef browser fill:#dbeafe,stroke:#2563eb,color:#0f172a
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#0f172a
    classDef code fill:#d1fae5,stroke:#10b981,color:#0f172a
    classDef store fill:#e2e8f0,stroke:#64748b,color:#0f172a
    classDef cloud fill:#ffedd5,stroke:#ea580c,color:#0f172a
    classDef ext fill:#f1f5f9,stroke:#94a3b8,color:#0f172a
```

Purple is the one step that uses a language model. Green is ordinary deterministic code. Grey is
storage.

Three containers run together. `app` serves both the React site and the JSON API, so there is
only one thing to deploy. `db` keeps saved charts on a volume, so they survive restarts.
`tunnel` is optional: it makes the app reachable from the internet without opening any port.

The app calls two outside services, **Anthropic** (for planning) and **ClinicalTrials.gov** (for
data). Both calls go out over my home internet connection. That is why this runs on my Mac and
not on a cloud host: ClinicalTrials.gov blocks the IP ranges of cloud providers (a Render
deployment got HTTP 403 on every request).

### What happens to one question

```mermaid
flowchart TD
    s1["<b>1. Browser</b><br/>AskBox → AskContext.submit → buildRequest<br/>POST /api/v1/visualize"]:::browser
    s2["<b>2. FastAPI</b><br/>VisualizeRequest checks the JSON<br/>enforce_rate_limit (20 per hour per IP)"]:::code

    subgraph loop["<b>3. Planner loop</b>: the only LLM step, at most 5 turns"]
        direction TB
        model["Claude reads the question and a<br/>system prompt built from the registries"]:::llm
        probes["Probe tools<br/>resolve_entity<br/>preview_result_size<br/>list_dimension_values"]:::code
        submit["submit_plan"]:::llm
        valid{"AnalysisPlan<br/>valid?"}
        model -->|"asks a tool"| probes
        probes -->|"real results"| model
        model --> submit
        submit --> valid
        valid -->|"no: the errors go back to Claude<br/>(at most 2 repairs)"| model
    end

    s4["<b>4. Executor</b> (no LLM)<br/>enforce_user_filters → _projection_for<br/>client.fetch (paged, cached) → normalize_study"]:::code
    s5["<b>5. aggregate</b><br/>group by the dimension, compute the measure<br/>(or exact_counts when the result is too big)"]:::code
    s6["<b>6. Build the answer</b><br/>resolve_visualization → build_group_by<br/>citations + ResponseMeta"]:::code
    s7["<b>7. Save</b><br/>repo.save_chart → Postgres<br/>chart_id added to the response"]:::store
    s8["<b>8. Browser</b><br/>ChartRenderer → ChartJsChart (bar)<br/>click a bar → CitationsPanel → trial link"]:::browser
    ctgov[("ClinicalTrials.gov")]:::ext

    s1 --> s2 --> model
    valid -->|yes| s4
    s4 --> s5 --> s6 --> s7 --> s8
    probes -.->|"cache first, then API"| ctgov
    s4 -.-> ctgov

    classDef browser fill:#dbeafe,stroke:#2563eb,color:#0f172a
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#0f172a
    classDef code fill:#d1fae5,stroke:#10b981,color:#0f172a
    classDef store fill:#e2e8f0,stroke:#64748b,color:#0f172a
    classDef ext fill:#f1f5f9,stroke:#94a3b8,color:#0f172a
```

| Module | Responsibility |
|---|---|
| `app/main.py` | Builds the app, starts the shared client and database connection, serves the React site. |
| `app/api/` | HTTP endpoints, saved-chart endpoints, rate limiting, error-to-status mapping. |
| `app/agent/` | The planner loop, the three probe tools, the system prompt, the repair cycle. |
| `app/models/` | The request, plan and response schemas. `plan.py` is the boundary between model output and trusted code. |
| `app/ctgov/` | ClinicalTrials.gov client (retries, paging, caching), query builder, normalization. |
| `app/analysis/` | Dimension and measure registries, the group-by engine, the network builder, citations. |
| `app/viz/` | Chart builders and the chart-type compatibility rules. |
| `app/executor.py` | Runs a validated plan and assembles the response. |
| `app/db/`, `alembic/` | Saved-chart table, database connection, migrations. |
| `frontend/` | The React app. |

---

## Run it with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and an Anthropic API key.

```bash
cp .env.example .env
# open .env and set:  ANTHROPIC_API_KEY=sk-ant-...

docker compose up --build
```

Then open <http://localhost:8000>.

The first build takes a couple of minutes (it builds the React app, then the Python image). On
every start the `app` container runs `alembic upgrade head`, which creates the `saved_charts`
table the first time, so there is nothing to set up by hand.

| Command | What it does |
|---|---|
| `docker compose up --build -d` | Rebuild and run in the background (use this after changing code). |
| `docker compose logs -f app` | Follow the server log. |
| `docker compose down` | Stop everything. Saved charts and the cache are kept. |
| `docker compose down -v` | Stop everything **and delete** saved charts and the cache. |

What is where: the `pgdata` volume holds the Postgres data, and the `cache` volume holds the
ClinicalTrials.gov response cache. Port 8000 is only bound to `127.0.0.1`, and Postgres has no
published port at all, so nothing is reachable from outside the machine unless you turn on the
tunnel below.

Handy URLs:

| URL | What it is |
|---|---|
| <http://localhost:8000/> | The React app |
| <http://localhost:8000/docs> | OpenAPI docs: the request and response schema, executable |
| <http://localhost:8000/api/v1/capabilities> | Machine-readable list of dimensions, measures and chart types |
| <http://localhost:8000/legacy> | The original single-file demo page |

```bash
curl -s localhost:8000/api/v1/visualize -H 'Content-Type: application/json' \
  -d '{"query":"How are melanoma trials distributed across phases?"}' | jq
```

### Make it public (Cloudflare Tunnel)

This puts the app on a real URL without opening a port or managing certificates. It needs a domain
whose DNS is on Cloudflare. Mine is `ctviz.rayyanhuda.com`.

1. In the Cloudflare dashboard, go to **Networking → Tunnels** and create a tunnel (type
   **Cloudflared**). Menu names move around, so look for "Tunnels". I named mine `ctviz`.
2. On the install page choose **Docker** and copy the token. It is the long `eyJ...` string after
   `--token`. **Don't run the `docker run` command shown there.** Compose runs the tunnel for you.
3. Put the token in `.env`. It is a secret, so never commit it or paste it anywhere:

   ```text
   CLOUDFLARE_TUNNEL_TOKEN=eyJ...
   ```

4. Add a published application route (public hostname): subdomain `ctviz`, your domain, service
   URL **`http://app:8000`**. The `http://` is required. `app` is the compose service name, which
   only resolves inside the compose network. Cloudflare creates the DNS record for you.
5. Start everything, including the tunnel:

   ```bash
   docker compose --profile public up -d --build
   curl https://ctviz.rayyanhuda.com/api/v1/health
   ```

Things to know:

- **The Mac has to be on and Docker has to be running**, or the site is down. Turn on "Start
  Docker Desktop when you sign in"; the containers restart themselves. `caffeinate -dims` keeps
  the Mac from sleeping.
- **It costs money if abused.** Every question calls the Anthropic API. Questions are limited to
  20 per hour per IP address, but that limit is a courtesy, not a security control. Set a monthly
  spend limit on the API key in the Anthropic Console.
- **If a token is ever exposed**, roll it in the Cloudflare dashboard and update `.env`.

---

## Run it without Docker

For working on the code, with auto-reload on both sides.

```bash
uv sync --extra dev                      # Python dependencies
cp .env.example .env                     # then set ANTHROPIC_API_KEY
uv run uvicorn app.main:app --reload     # API on http://localhost:8000

cd frontend
npm install
npm run dev                              # UI on http://localhost:5173, proxies /api to :8000
```

- **Saved charts are off** unless a database is configured. Start any Postgres, set
  `CTGOV_VIZ_DATABASE_URL=postgresql://user:password@localhost:5432/dbname` in `.env`, then
  create the table once with `uv run alembic upgrade head`. Without a database the API works
  exactly as before and History shows a "switched off" message.
- **Let FastAPI serve the UI** (instead of the Vite dev server) with `npm run build`. It writes
  `frontend/dist`, which the server picks up on start.
- **After changing a Pydantic model**, run `npm run gen:api` in `frontend/`. It regenerates the
  TypeScript types from the backend's OpenAPI file, and `npm run typecheck` then points at every
  place in the UI that no longer matches.

`ANTHROPIC_API_KEY` is the only required setting. Everything else has a default and can be
overridden with a `CTGOV_VIZ_` prefix, e.g. `CTGOV_VIZ_MODEL`, `CTGOV_VIZ_MAX_STUDIES`,
`CTGOV_VIZ_CACHE_TTL_SECONDS`, `CTGOV_VIZ_RATE_LIMIT_PER_HOUR`
(see [`app/config.py`](app/config.py)).

The test suite runs offline and needs **no API key**:

```bash
uv run pytest            # 321 tests, about 5 seconds, no network
uv run pytest -m live    # 7 more, against the real APIs (needs the key and the internet)
```

---

## Using the app

1. **Ask.** Type a question, or click an example. The Ask page shows a welcome view first, and
   after that the filters and the question box sit together at the top with the answer below.
2. **Filters (optional).** Drug, condition, sponsor, phase, from-year and to-year narrow *which*
   trials are fetched. They are hard constraints: they beat anything the agent would infer.
3. **Read the chart.** Next to it, the *Agent interpretation* card says how the question was
   understood, what one unit means, what was assumed, and how much of the data was analysed.
4. **Click a bar** (or a node or a table row) to see its source trials directly under the chart.
   Each excerpt is the exact value ClinicalTrials.gov returned, and the NCT ID links to the trial.
5. **Look under the hood.** The tabs under the chart show the data table, the raw JSON response,
   and the exact API queries, which you can open to reproduce the data by hand.
6. **Saved charts.** Every answer is saved as a snapshot at `/c/<id>`. Share the link, **Refresh
   with live data** (see below), or delete it. The **History** page lists everything.
7. **Links that ask for you.** `/?q=...&drug=...&phase=PHASE3&start_year=2015` runs a question
   when the page opens.

---

## API

| Endpoint | What it does |
|---|---|
| `POST /api/v1/visualize` | Question in, visualization specification out. Saves the chart if a database is configured. |
| `POST /api/v1/plan` | Runs only the planner and returns the plan, with no data fetch. |
| `GET /api/v1/capabilities` | The dimensions, measures, metrics, filters and chart types this service supports. |
| `GET /api/v1/health` | Liveness, and whether the key and database are configured. |
| `GET /api/v1/charts?limit=&offset=` | Saved charts, newest first (summaries only). |
| `GET /api/v1/charts/{id}` | One saved chart, exactly as it was generated. |
| `POST /api/v1/charts/{id}/refresh` | Re-runs the saved plan on live data and saves the result as a new chart. |
| `DELETE /api/v1/charts/{id}` | Deletes a saved chart. |

`visualize`, `plan` and `refresh` are rate limited. The `/charts` endpoints return `503
configuration_error` when no database is configured.

### Request schema (inputs)

Only `query` is required. Structured fields are optional and sit at the top level.

| Field | Type | Notes |
|---|---|---|
| `query` | string, 3–500 chars | **Required.** The question, in plain language. |
| `drug_name` | string | Drug / intervention terms. |
| `condition` | string | Conditions or diseases. |
| `sponsor` | string | Sponsor names. |
| `country` | string | Full names as ClinicalTrials.gov spells them (`"South Korea"`). |
| `trial_phase` | enum | `EARLY_PHASE1`, `PHASE1`…`PHASE4`, `NA`. |
| `status` | enum | `RECRUITING`, `COMPLETED`, … (14 values). |
| `study_type` | enum | `INTERVENTIONAL`, `OBSERVATIONAL`, `EXPANDED_ACCESS`. |
| `intervention_type` | enum | `DRUG`, `BIOLOGICAL`, `DEVICE`, … (11 values). |
| `sponsor_class` | enum | `INDUSTRY`, `NIH`, `FED`, … (9 values). |
| `start_year`, `end_year` | integer, 1900–2100 | Inclusive bounds on trial start year. |
| `options` | object | See below. |

`options`: `max_studies` (int, ≤20000), `include_citations` (bool, default true),
`citations_per_datum` (int 0–25, default 3), `include_plan` (bool, default true),
`preferred_visualization` (chart type hint).

**Validation.** Unknown fields are rejected, not ignored (`extra="forbid"`). Enum values are
checked against the API's own vocabularies, and `start_year > end_year` is an error. A single
string is accepted anywhere a list is expected, so `"drug_name": "aspirin"` works.

**Precedence.** Structured fields are *hard constraints*. They are given to the planner as
constraints and then re-applied by code afterwards, so the model cannot change them. The response
reports user-supplied and inferred filters separately in `meta.filters_applied`.

### Response schema (outputs)

```jsonc
{
  "status": "ok",                    // or "no_data" — never a fabricated chart
  "question": "…",                   // echoed back
  "visualization": {
    "type": "bar_chart",
    "title": "Melanoma Interventional Trials by Phase",
    "subtitle": "…",
    "encoding": {                    // which row key feeds which visual channel
      "x": { "field": "phase", "type": "ordinal", "title": "Trial Phase" },
      "y": { "field": "trial_count", "type": "quantitative",
             "title": "Number of Trials", "unit": "trials" }
    },
    "data": [
      { "phase": "Phase 3", "trial_count": 112, "share_pct": 6.4,
        "contributing_trial_count": 112,
        "citations": [
          { "nct_id": "NCT02506153",
            "field": "protocolSection.designModule.phases",
            "excerpt": "PHASE3",
            "context": "A Study of Pembrolizumab Versus Placebo…",
            "url": "https://clinicaltrials.gov/study/NCT02506153" }
        ] }
    ]
  },
  "meta": { /* see below */ },
  "plan": { /* the validated analysis plan */ },
  "citation_index": { "NCT02506153": { "title": "…", "url": "…" } },
  "chart_id": "5rB78lyeE9I"          // present when the chart was saved
}
```

#### Rendering contract

A renderer should not have to guess:

- **`encoding` names the row keys.** Read `encoding.x.field` to learn which key holds the x value,
  rather than hardcoding key names per chart type. Only the channels a chart uses are populated.
- **Rows are flat dicts** keyed by dimension id and measure id.
- **Charts carry `data`; `network_graph` carries `nodes` and `edges`** instead (with
  `encoding.node` / `encoding.edge` naming their keys). Both keys always exist, so a client can
  branch on which is populated.
- **`geo_map` populates both** `encoding.location` (`country_iso3`) and `encoding.x`/`y`, so a
  client without map support renders ranked bars from the same payload.

#### `meta`

| Field | Why it is there |
|---|---|
| `interpretation` | How the question was understood. |
| `assumptions` | Choices the user did not specify and might want changed: a date window, a synonym, a top-k cut. |
| `filters_applied.user` / `.inferred` | Which constraints came from the caller and which the planner derived. |
| `counting_semantics` | What one unit means, **including whether a trial can land in several buckets**. |
| `coverage` | `strategy`, `total_matching`, `analyzed`, `truncated`, `per_cohort[]`, `records_missing_dimension`, `categories_omitted`. |
| `measure`, `sort`, `time_granularity` | Units, ordering, and time bucket size. |
| `ctgov_requests[]` | **The API parameters sent.** Replaying them reproduces the data by hand. |
| `warnings` | Truncation, chart-type substitutions, sparse data. |

#### Visualization types

`bar_chart`, `grouped_bar_chart`, `stacked_bar_chart`, `time_series`, `scatter_plot`, `histogram`,
`geo_map`, `network_graph`, `kpi`, `table`.

`kpi` matters as much as the charts: the assignment asks the system to decide *whether* a
visualization is needed, and "how many trials is Pfizer running for lung cancer?" wants a number,
not just a bar.

### Errors

```json
{ "error": "upstream_error", "message": "…", "remedy": "…" }
```

| Status | Meaning |
|---|---|
| `422` | The planner could not produce a valid plan, or the question is out of scope. |
| `429` | Rate limit reached. |
| `404` | No saved chart with that id. |
| `502` | ClinicalTrials.gov failed or refused the request. |
| `503` | Missing configuration (no API key, or no database for `/charts`). |
| `500` | Anything unexpected. |

---

## How it works

The planner is a small loop. Claude can call three **probe tools** to check the real registry
before committing (`resolve_entity`: how does ClinicalTrials.gov spell this drug? `preview_result_size`:
how many trials would these filters match? `list_dimension_values`: what values does this field
actually hold?). It then calls `submit_plan`, whose input schema is the `AnalysisPlan` model
itself. The plan is validated; if it fails, the error text goes back to Claude as the tool result
and it tries again (at most 2 repairs, at most 5 turns). Only a valid plan ever reaches the executor.

The executor runs the plan with no language model: it fetches the trials, flattens them into
`TrialRecord`s, groups and counts them, builds the chart specification and attaches citations.

---

## Key design decisions and tradeoffs

### 1. The model emits a plan, never data

Everything else follows from this. The planner's only output is an `AnalysisPlan` validated
against **closed registries**: 24 dimensions, 6 measures, 6 metrics, 10 chart types, with
`extra="forbid"` on every model. A hallucinated `"sponsor_country"` dimension or a misremembered
`"PHASE_III"` fails validation.

Validation errors are returned to the model for **repair** (max 2 attempts), which turns most
failures into self-correction. This fired on the very first live run: the model passed
`assumptions` as a JSON-encoded string instead of an array, and fixed it on the retry.

*Tradeoff:* a closed vocabulary cannot answer a question outside the registry. The alternative is
letting the model emit arbitrary field paths or code. That buys a broader range of questions at
the cost of the guarantee that makes the output factual every time.

### 2. A registry-driven engine, not one path per question

Every bar, line, map and table comes out of one `aggregate()` function. A dimension is
`(id, extractor, multi_valued, source_field, api_fields, …)`; adding a way to slice the data is
one registry entry, with no new branch in the aggregator, the viz builders, the planner prompt,
the API schema, or the docs, **all of which read the registry**. The planner's system prompt is
*generated* from it, so prompt and code cannot drift apart.

### 3. Comparisons are cohorts, not a special case

"Pembrolizumab vs nivolumab", "Germany vs Japan", "Pfizer vs Novartis" are all the same shape:
retrieval is a list of named **cohorts**, each fetched separately and tagged, and `cohort` is
itself a dimension. Setting `series_dimension: "cohort"` produces a grouped chart. One concept
covers every comparison question without comparison-specific code.

### 4. Two retrieval strategies

`fetch_and_aggregate` pages through records and aggregates locally. But analyzing the first 5,000
of 50,000 matches and presenting the result as complete would be wrong. So when retrieval
truncates *and* the grouping dimension is a low-cardinality enum, the executor switches to
**`exact_counts`**: one request per bucket using Essie `filter.advanced`, returning the true total
*and* a sample to cite in the same response (`countTotal` and `pageSize` are independent).

Either way `meta.coverage.strategy` says which ran, and truncation is disclosed.

### 5. Search terms are passed through

Measured against the live API: `lung cancer` matches 14,553 studies, `"lung cancer"` only 13,326;
quoting suppresses the API's own synonym and MeSH expansion. So free text is passed **unquoted**,
and multiple terms are parenthesised (`(a) OR (b)`), which was verified to give correct union
semantics while keeping expansion.

Free text reaching an Essie filter clause is stripped of `[]()"` so a value like
`Boston] OR AREA[Phase` cannot restructure the query.

### 6. Networks use MeSH terms

Raw intervention names fragment badly: `Nivolumab`, `Nivolumab 240mg` and
`Nivolumab + Relatlimab` are three different strings. `derivedSection.interventionBrowseModule`
gives NLM-normalized terms, which is what makes a drug network meaningful. A raw co-occurrence
graph over thousands of trials is messy, so edges below `min_edge_weight` and all but the
highest-degree `max_nodes` are dropped, and both cuts are reported in `meta.warnings`.

### 7. Deterministic guards behind the model

A schema-valid plan can still be a bad plan, so the executor checks it: a `time_series` over a
non-temporal dimension, a choropleth over sponsors, a `grouped_bar_chart` with nothing to group
by, or a network over `phase`. Each is either rejected at validation or replaced with the default
for that analysis, with the substitution recorded in `meta.warnings`.

### 8. Citations are reproducible

An excerpt is the value the API returned at `field`: the literal `"PHASE3"`, `"United States"`,
`"2016-04-15"`. `context` quotes the trial's brief title. No part of a citation is
model-generated.

### 9. Saved charts are snapshots, and a refresh never calls the model

Every successful answer is stored in Postgres: the request, the validated plan, and the full
response. Opening `/c/<id>` shows that stored snapshot exactly as it was, even if
ClinicalTrials.gov has changed since. **Refresh** re-runs the *stored plan* through the executor,
which costs no model call, and saves the result as a **new** row whose `refreshed_from_id` points
at the old one. Rows are never edited, so a chart's history is always intact, and the page can
show how the matching-trial count moved between the two versions. If saving fails, the user still
gets the answer.

### 10. A tunnel from my machine instead of a cloud host

ClinicalTrials.gov's firewall blocks cloud IP ranges, so a cloud deployment can be refused on
every request while the identical request works from a laptop. Docker Compose plus a Cloudflare
Tunnel makes the app reachable at a real URL while its outbound calls leave from a home
connection. *Tradeoff:* the site is only up while the machine is on. In production I would
mirror the registry instead (see below).

---

## Limitations and what I would improve with more time

**Known limitations**

1. **MeSH auto-tagging is hard.** NLM's automatic indexing produces odd associations: the myeloma
   co-occurrence graph shows "Calcium Dobesilate" with high weight, which is an indexing product,
   not myeloma pharmacology. Mitigation today: `intervention_name` is available as an alternative
   dimension. A fix needs a curated drug vocabulary (RxNorm/ChEMBL).
2. **`geo_map` is drawn as ranked bars, not a choropleth.** The *specification* is
   choropleth-ready (ISO3 per row), so this is a front-end limitation and would be easy to add.
3. **`exact_counts` only applies to enum dimensions.** A high-cardinality breakdown (sponsors,
   drugs) over a very large result set still truncates.
4. **No cross-field statistics.** No correlations, significance testing, or trend fitting. The
   service counts and groups; it does not infer.
5. **Planning costs one to three model calls.** A cold question takes roughly 10–20 seconds end
   to end (one measured run: 12.5 s planning plus 2.4 s fetching data). A repeat is much faster
   because the ClinicalTrials.gov responses are cached for 24 hours.
6. **Retrieval is capped at 5,000 trials per cohort by default.** Raising it is a request option,
   but very broad questions are slow.
7. **Single-turn.** No conversational refinement of a previous answer, and it cannot ask the user
   a clarifying question, so it has to state its assumptions.
8. **No authentication.** Anyone with the URL can ask questions (rate limited), see the History
   page, and delete saved charts. Share links are random, but the list is not private. Fine for a
   demo; a real deployment would add accounts and per-user charts.
9. **It runs from my own machine.** The public URL is only up while the Mac is on.
10. **Front-end tests.** The backend has 321 tests; the React app has none. It was exercised in a
    real browser, but the stacked-bar and table chart types were not looked at.

**What I would do next:** mirror the registry into my own Postgres (the AACT dataset, synced
nightly) so planning and counting no longer depend on one public API or on where the server is
hosted; add accounts; add unit tests for the chart-config functions.

---

## Tools used

**Tools.** Claude Code for planning, building boilerplate, validation checks, the example folder,
some comments, formatting for readability, wording in this file, and refining my ideas for how the
backend should be built.

**How correctness was validated.**

1. **API assumptions were verified against the live API before being coded**, not recalled. This
   changed the design repeatedly: `stats/field/values` turned out not to accept `query.*`
   parameters; quoting search terms turned out to *reduce* recall; `countTotal` and `pageSize`
   turned out to be independent. Enum vocabularies and the field projection list were pulled from
   `/studies/enums` and verified.
2. **321 offline tests** over real captured data, with network access blocked so "offline" is
   enforced. They cover the planner (with a stubbed model), the executor, the saved-chart
   endpoints (on SQLite), and the page-serving routes.
3. **7 live tests** asserting the upstream assumptions the design rests on, including a real
   model probing before it plans.
4. **Renderers were checked in a real browser** (first the original demo page, then the React
   app, driven with Playwright). This caught bugs no unit test would have: a blank
   network canvas (the container was `display:none` when the canvas measured itself, so it sized to
   zero); a geo chart where Chart.js dropped every other country label; a histogram rendering
   sideways, which hides a distribution's shape; and log-scaled bins over an integer metric
   producing labels like `1–1` and `2–2`.
5. **The deployment was tested the way it runs:** the Docker image was built, started, asked a
   real question, restarted from scratch to confirm saved charts persist, and then reached through
   the public URL.

**Designed deliberately vs. generated.** The architecture (the model as a compiler, the plan
schema as the trust boundary, the dimension and measure registries, cohorts as comparisons, the
two retrieval strategies, the citation model, snapshot-and-refresh charts) was designed first.
Mechanical code (the country map, enum tables, Chart.js configuration, docstring prose) was
generated and reviewed. Several things were corrected during implementation and testing: the
Unknown-bucket ordering bug under descending sort, the network-eligibility flag replacing a bad
`multi_valued` heuristic, and the rendering bugs above.
