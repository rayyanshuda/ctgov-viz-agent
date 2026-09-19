# ClinicalTrials.gov Query-to-Visualization Agent

Answers natural-language questions about clinical trials with **structured visualization
specifications** backed by live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) data.

## How to run

Requires Python 3.11+ and an Anthropic API key.

**1. Install**

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

<sub>Without `uv`: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`</sub>

**2. Configure**

```bash
cp .env.example .env
# then edit .env and set:  ANTHROPIC_API_KEY=sk-ant-...
```

`ANTHROPIC_API_KEY` is the only required setting. Everything else has a working default and is overridable with a `CTGOV_VIZ_` prefix — `CTGOV_VIZ_MODEL`, `CTGOV_VIZ_MAX_STUDIES`,
`CTGOV_VIZ_CACHE_DIR`, `CTGOV_VIZ_CACHE_TTL_SECONDS`, `CTGOV_VIZ_HTTP_TIMEOUT_SECONDS`
(see [`app/config.py`](app/config.py)).

**3. Start**

```bash
uv run uvicorn app.main:app --reload
```

Then open:

| URL | What it is |
|---|---|
| <http://localhost:8000/> | Interactive demo UI |
| <http://localhost:8000/docs> | OpenAPI docs — the request/response schema, executable |
| <http://localhost:8000/api/v1/capabilities> | Machine-readable list of dimensions, measures and chart types |

```bash
curl -s localhost:8000/api/v1/visualize -H 'Content-Type: application/json' \
  -d '{"query":"How are melanoma trials distributed across phases?"}' | jq
```

The test suite runs offline and needs **no API key**:

```bash
uv run pytest            # 298 tests, ~3s, no network
uv run pytest -m live    # 6 more, against the real ClinicalTrials.gov API
```

---

## Deploying

`render.yaml` configures a free Render web service, so deploying is: **New > Blueprint >
pick this repo**, then paste `ANTHROPIC_API_KEY` when prompted. Render reads the build and
start commands from that file.

Two things the blueprint handles that would otherwise bite:

- **Ephemeral disk.** The response cache is redirected to `/tmp`, since Render's free tier
  wipes the filesystem on restart. The cache is only an optimisation, so losing it costs a
  little latency and nothing else.
- **Rate limiting.** `/visualize` and `/plan` call the Anthropic API, so a public URL is a
  way for anyone with the link to spend the owner's credits. Both are capped per client
  (20 questions/hour by default, `CTGOV_VIZ_RATE_LIMIT_PER_HOUR`), returning a `429` that
  says when to retry. `/health` and `/capabilities` cost nothing to serve and are not
  limited. The client is identified by `X-Forwarded-For`, because behind a proxy every
  request otherwise shares one address — that header is spoofable, which is acceptable for
  a spend guard but would not do as a security control.

Locally the limit is off the critical path; set `CTGOV_VIZ_RATE_LIMIT_ENABLED=false` to
disable it entirely.

---

## Request schema (inputs)

Only `query` is required. Structured fields are optional and sit at the top level.

| Field | Type | Notes |
|---|---|---|
| `query` | string, 3–500 chars | **Required.** The question, in plain language. |
| `drug_name` | string | Drug / intervention terms. |
| `condition` | string | Conditions or diseases. |
| `sponsor` | string| Sponsor nam es. |
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

**Validation.** Unknown fields are rejected not ignored (`extra="forbid"`), enum values are checked against the API's vocabularies, and `start_year > end_year` is an error. An empty string is accepted anywhere a list is expected, so `"drug_name": "aspirin"` works.

**Precedence.** Structured fields are *hard constraints*. They are given to the planner as constraints and then re-applied deterministically afterwards, so no amount of model enthusiasm can change them. The response reports user-supplied and inferred filters separately in `meta.filters_applied`.

---

## Response schema (outputs)

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
  "citation_index": { "NCT02506153": { "title": "…", "url": "…" } }
}
```

### Rendering contract

A renderer should not have to guess:

- **`encoding` names the row keys.** Read `encoding.x.field` to learn which key holds the x value, rather than hardcoding key names per chart type. Only the channels a chart uses are populated.
- **Rows are flat dicts** keyed by dimension id and measure id.
- **Charts carry `data`; `network_graph` carries `nodes` and `edges`** instead (with `encoding.node` / `encoding.edge` naming their keys). Both keys always exist, so a client can branch on which is populated.
- **`geo_map` populates both** `encoding.location` (`country_iso3`) and `encoding.x`/`y`, so a client without map support renders ranked bars from the same payload.

### `meta`

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

### Visualization types

`bar_chart`, `grouped_bar_chart`, `stacked_bar_chart`, `time_series`, `scatter_plot`, `histogram`,
`geo_map`, `network_graph`, `kpi`, `table`.

`kpi` matters as much as the charts: the assignment asks the system to decide *whether* a visualization is needed, and "how many trials is Pfizer running for lung cancer?" wants a number, not just a bar.

### Errors

```json
{ "error": "upstream_error", "message": "…", "remedy": "…" }
```

`422` planning/validation · `502` upstream API failure · `503` missing configuration.

---

## How it works

```
question + structured filters
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ PLANNER (app/agent/)                    the only LLM step  │
│  bounded tool loop, ≤5 iterations                          │
│   • resolve_entity
│   • preview_result_size   is this cohort empty or huge?    │
│   • list_dimension_values what values actually exist?      │
│   • submit_plan           terminal, Pydantic-validated     │
└───────────────────────────────────────────────────────────┘
        │  AnalysisPlan: closed enums, extra="forbid"
        ▼
┌───────────────────────────────────────────────────────────┐
│ EXECUTOR (app/executor.py)              zero LLM           │
│  fetch → normalize → aggregate / build graph               │
│        → attach citations → assemble response              │
└───────────────────────────────────────────────────────────┘
```

| Module | Responsibility |
|---|---|
| `app/agent/` | Planner loop, probe tools, prompt, repair cycle. |
| `app/models/plan.py` | The plan schema: the boundary between probabilistic and deterministic. |
| `app/ctgov/` | API client (retries, pagination, caching), query builder, normalization. |
| `app/analysis/` | Dimension & measure registries, group-by engine, network builder, citations. |
| `app/viz/` | Chart builders and the compatibility matrix. |
| `app/executor.py` | Orchestration: runs a validated plan, assembles the response. |

---

## Key design decisions and tradeoffs

### 1. The model emits a plan, never data

Everything else follows from this. The planner's only output is an `AnalysisPlan` validated against **closed registries**; 24 dimensions, 6 measures, 6 metrics, 10 chart types, with
`extra="forbid"` on every model. A hallucinated `"sponsor_country"` dimension or a misremembered
`"PHASE_III"` fails validation.

Validation errors are returned to the model for **repair** (max 2 attempts), which turns most failures into self-correction. This fired on the very first live run: the model passed
`assumptions` as a JSON-encoded string instead of an array, and fixed it on the retry.

*Tradeoff:* a closed vocabulary cannot answer a question outside the registry. The alternative is letting the model emit arbitrary field paths or code, buys ore broader range of questions that can be asked at the cost of the guarantee that makes the output factual all the time.

### 2. A registry-driven engine, not one path per question

Every bar, line, map and table comes out of one `aggregate()` function. A dimension is `(id, extractor, multi_valued, source_field, api_fields, …)`; adding a way to slice the data is one
registry entry, with no new branch in the aggregator, the viz builders, the planner prompt, the API schema, or the docs, **all of which read the registry**. The planner's system prompt is
*generated* from it, so prompt and code cannot drift apart.

### 3. Comparisons are cohorts, not a special case

"Pembrolizumab vs nivolumab", "Germany vs Japan", "Pfizer vs Novartis" are all the same shape: retrieval is a list of named **cohorts**, each fetched separately and tagged, and `cohort` is itself a dimension. Setting `series_dimension: "cohort"` produces a grouped chart. One concept covers every comparison question without comparison-specific code.

### 4. Two retrieval strategies

`fetch_and_aggregate` pages through records and aggregates locally. But analyzing the first 5,000 of 50,000 matches and presenting the result as complete would be wrong to pick as a subset. So when retrieval truncates *and* the grouping dimension is a low-cardinality enum, the executor switches to **`exact_counts`**: one request per bucket using Essie `filter.advanced`, returning the true total *and* a sample to cite in the same response (`countTotal` and `pageSize` are independent).

Either way `meta.coverage.strategy` says which ran, and truncation is disclosed.

### 5. Search terms are passed through

Measured against the live API: `lung cancer` matches 14,553 studies, `"lung cancer"` only 13,326; quoting suppresses the API's own synonym and MeSH expansion. So free text is passed **unquoted**, and multiple terms are parenthesised (`(a) OR (b)`), which was verified to give correct union semantics while keeping expansion.

Free text reaching an Essie filter clause is stripped of `[]()"` so a value like `Boston] OR AREA[Phase` cannot restructure the query.

### 6. Networks use MeSH terms

Raw intervention names fragment badly — `Nivolumab`, `Nivolumab 240mg` and `Nivolumab + Relatlimab` are three different strings. `derivedSection.interventionBrowseModule` gives NLM-normalized terms, which is what makes a drug network meaningful. A raw co-occurrence graph over thousands of trials is messy and lots of data to handle, so edges below `min_edge_weight` and all but the highest-degree `max_nodes` are dropped, and both cuts are reported in `meta.warnings`.

### 7. Deterministic guards behind the model

A schema-valid plan can still be a bad plan, so the executor checks it: a `time_series` over a non-temporal dimension, a choropleth over sponsors, a `grouped_bar_chart` with nothing to group by, or a network over `phase`. Each is either rejected at validation or replaced with the default for that analysis, with the substitution recorded in `meta.warnings`.

### 8. Citations are reproducible

An excerpt is the value the API returned at `field`, the literal `"PHASE3"`, `"United States"`, `"2016-04-15"`, and `context` quotes the trial's brief title. No part of a citation is model-generated.

---

## Limitations and what I would improve with more time

**Known limitations**

1. **MeSH auto-tagging is hard.** NLM's automatic indexing produces weird associations: the myeloma co-occurrence graph shows "Calcium Dobesilate" with high weight, which is an indexing product, not myeloma pharmacology. Mitigation today: `intervention_name` is available as an alternative dimension. A fix needs a curated drug vocabulary (RxNorm/ChEMBL).
2. **The demo renders `geo_map` as ranked bars, not a choropleth.** The *specification* is choropleth-ready (ISO3 per row), so this is a demo limitation, it would be very easy to add this to the backend.
3. **`exact_counts` only applies to enum dimensions.** A high-cardinality breakdown (sponsors, drugs) over a very large result set still truncates.
4. **No cross-field statistics.** No correlations, significance testing, or trend fitting. The service counts and groups; it does not infer.
5. **Planning costs one to three LLM calls** (≈3–8s). Uncached, a cold `/visualize` is 5–15s.
6. **Retrieval is capped at 5,000 trials per cohort by default.** Raising it is a request option, but very broad questions are slow.
7. **Single-turn.** No conversational refinement of a previous answer. Currently, can't ask the user any clarifying questions, it has to make assumptions.

---

## Tools used

**Tools.** Claude Code for planning, building the boiler plate, validation checks, example folders, some comments, helped format the code for readability, helped with this file's wording, and refined the logic from my ideas for how the backend should be built.

**How correctness was validated.**

1. **All API assumption was verified against the live API before being coded**, not recalled. This changed the design repeatedly: `stats/field/values` turned out not to accept `query.*` parameters; quoting search terms turned out to *reduce* recall; `countTotal` and `pageSize` turned out to be independent. Enum vocabularies and the 25-field projection list were pulled from `/studies/enums` and verified.
2. **298 offline tests** over real captured data, with network access blocked so "offline" is enforced.
3. **6 live tests** asserting the upstream assumptions the design rests on.
4. **Every renderer path was screenshotted** in a real browser. This caught four bugs that no unit test would have: a blank network canvas (the container was still `display:none` when the canvas measured its own width, so it sized to zero); a geo chart where Chart.js dropped every other country label; a histogram rendering sideways, which makes a distribution's shape much harder to read; and log-scaled bins over an integer metric producing labels like `1–1` and `2–2`, since no trial can enroll 1.29 participants.

**Designed deliberately vs. generated.** The architecture, LLM-as-compiler, the plan schema as the trust boundary, the dimension/measure registries, cohorts-as-comparisons, the dual retrieval strategy, the citation model, was designed first. Mechanical code (the country map, enum tables, Chart.js configuration, docstring prose) was generated and reviewed. Several things were corrected during implementation and testing: the Unknown-bucket ordering bug under descending sort, the network-eligibility flag replacing a bad `multi_valued` heuristic, and the two rendering bugs above.