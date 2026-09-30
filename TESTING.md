# Testing

## How to run

```bash
cd backend
uv sync
uv run pytest                          # 100 cases, about 10 seconds, no network or keys needed
uv run pytest --cov --cov-report=term  # with coverage (about 80% of backend/app)
LIVE_LLM_URL=http://localhost:8080 GEMINI_MODEL=gemini-3.5-flash GROQ_MODEL=openai/gpt-oss-120b \
  uv run pytest tests/test_llm.py -k live   # optional check against a running Bifrost

cd ../frontend
npm run typecheck && npm run build
```

CI runs the same backend and frontend checks plus `docker compose build` on every push and pull request (`.github/workflows/ci.yml`).

## Plan

| File | What is covered |
| --- | --- |
| `test_core.py` | Query and period parsing, normalisers, catalog and vector search, MCP client, snapshot fallback |
| `test_analytics.py` | Hand-calculated per-cent change, Pearson correlation, cross-dataset alignment, Excel source |
| `test_quality.py` | Duplicates, nulls, required columns, outliers, coverage notes, every real snapshot |
| `test_llm.py` | Hallucination detection, structured output, revision loop, consistency, Gemini-to-Groq fallback, and the Bifrost config (logging on, logs and settings in the same Postgres database) |
| `test_agents.py` | Full agent graph, replan after failed fetch, revise, search outage, chat routing |
| `test_api.py` | Validation, background jobs, WebSocket replay, conversations and history |
| `test_performance.py` | 10,000-row normalise and summarise under 3 seconds, 40 concurrent API requests with p95 under 1 second |

Tests use a temporary SQLite database with foreign keys enforced (`conftest.py`). Government APIs, the MCP service and the LLM gateway are replaced with fakes at the module boundary, so the real parsing, statistics, graph routing and grounding code still runs.

## Methodology

The suite follows the same boundaries as the application:

1. Unit tests verify parsing, cleaning, statistics and grounding with small deterministic inputs.
2. Integration tests run the LangGraph workflow with fake external services but real agent nodes, graph edges and fallback logic.
3. API tests create background jobs, persist results and reconnect through WebSockets.
4. Performance tests enforce generous CI budgets for large datasets and concurrent requests.
5. A running stack is checked by submitting a query in the UI, including the gov-mcp outage case.

External systems are mocked only at their network boundary. This keeps normalisation, planning, analytics, persistence and report validation under test while avoiding flaky government APIs, quotas and LLM variation in the default suite.

## Hallucination detection

Every briefing passes through `check_grounding` before it is shown. The fact list holds every charted value, latest value, start value, change and correlation the analytics step computed. Each number in the briefing and insights must match a fact, with these allowances:

- Years and period labels (`2020`, `2024-Q3`) are not claims.
- Rounding must match the stated precision: `14%` matches 14.4, `14.9%` does not.
- Unit scales are accepted: `187.3 thousand` matches 187,300.
- Unsigned numbers match by magnitude ("fell by 300" matches -300), but an explicit sign must agree.
- Ranges (`10-15`) and numbers inside series labels ("15 - 19 Years") are not claims.

A failed check triggers one revision that lists the unsupported numbers. If that still fails, the deterministic template briefing is used and the UI shows the grounding status. The same facts always produce the same summary, and the template path cannot fail its own check. The optional live test calls the real gateway twice with the same facts and requires both answers to pass.

The tests include invented values, incorrect signs, valid rounded values, scaled units, period labels and numbered series names. They also drive the full graph through a hallucinated first draft and confirm that the revision replaces it with a grounded report.

## Accuracy and consistency

Statistical functions are checked against hand-calculated expectations rather than LLM output:

- A change from 200 to 250 must be 25%.
- A series crossing from 2,700 to -300 must report an absolute change of -3,000, not a misleading percentage.
- Perfectly aligned increasing and decreasing series must produce correlations of 1.0 and -1.0.
- Correlation needs at least four shared periods and skips adjusted/unadjusted variants of the same series.
- Real snapshot fixtures verify expected values after parsing and normalisation.

Consistency tests confirm that identical data produces identical facts, charts and metrics; the same model response produces the same parsed report; and the deterministic fallback always passes grounding. LLM prompts run at low temperature, while the optional live check verifies grounding rather than requiring identical prose.

## Data quality

Quality tests cover missing markers, malformed numbers, duplicate rows, absent required columns, repeated periods, stale coverage and robust outlier detection. Outliers are flagged rather than removed. Every bundled snapshot is loaded in the suite to catch format drift or broken fixtures.

The tests also verify hierarchical tables. Section headings and indented rows must remain separate so age or sector breakdowns are not averaged into headline totals. Every returned dataset includes row counts, coverage, null counts and cleaning notes for display in the frontend.

## Agent and failure scenarios

Integration tests exercise the decisions that make the workflow agentic:

- The coordinator may select only dataset keys returned by search.
- A single-source plan adds a second provider for cross-checking where possible.
- Failed extraction tries another candidate and can replan once.
- An unavailable gov-mcp service falls back to pinned snapshots.
- Invalid LLM output falls back to ranked search or a deterministic report.
- Unsupported report numbers enter the revision branch.
- General conversation avoids unnecessary dataset fetching.

Agent tests confirm that thought, action and observation events are emitted. API tests then verify that events are stored and replayed to a WebSocket client that connects after the job has started.

## Performance and load

`test_performance.py` uses limits intended to detect regressions without making CI timing fragile:

| Scenario | Pass condition |
| --- | --- |
| Normalise 10,000 source rows | Completes in under 3 seconds and preserves all valid rows |
| Summarise two 10,000-row datasets | Completes in under 3 seconds and produces charts |
| Submit 40 analyses with 10 workers | Every request returns 200 and p95 submission latency is below 1 second |

The load test stubs the expensive agent work. It measures API acceptance, background scheduling and persistence rather than external provider latency.

## End-to-end checks

Submit a query in the UI at http://localhost:5173 and confirm the agent activity, datasets, chart, and grounding status. The sample queries in the README are the set used for that check.

The manual outage scenario stops gov-mcp before submission. A pass requires a visible search failure, local snapshot fallback, a completed report and a note that live data was unavailable. This demonstrates graceful degradation instead of hiding the failure.

## Results

The backend suite is 100 cases. It passes with no network or API keys, in about 10 seconds, at about 80% line coverage of `backend/app`. One case reads `bifrost/config.json` and checks that request logging is on and that both the log store and the config store use the `sgstats` Postgres database. The Gemini-to-Groq fallback is checked on the LangChain client, without calling the gateway. The lower coverage is live HTTP (government APIs, embedding jobs, Postgres-only vector queries), which the end-to-end runs exercise instead.

End-to-end runs of the sample queries in the README, plus a gov-mcp outage, all completed in 17 to 34 seconds with grounding passed. With the data service stopped, search failure is reported, bundled snapshots are loaded, and the briefing says the service was unreachable.

## Continuous integration

GitHub Actions runs three jobs:

1. Backend tests on Python 3.12, producing JUnit and XML coverage artifacts.
2. Frontend TypeScript checking and a production Vite build on Node 20.
3. Docker Compose validation and image builds after both test jobs pass.

The live LLM and government API checks remain opt-in because credentials, quotas and upstream availability would make pull-request checks non-deterministic.
