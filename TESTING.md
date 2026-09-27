# Testing

## Summary

| Measure | Result |
| --- | --- |
| Backend tests | 102 passed, 1 skipped (the opt-in live LLM test) |
| Run time | About 10 seconds, no network or API keys needed |
| Line coverage | 80% of `backend/app` |
| Frontend | `tsc --noEmit` and `vite build` pass |
| End-to-end | 6 sample queries plus an outage scenario run against the live Docker stack, all completed with grounded briefings |

Commands:

```bash
cd backend
uv run pytest                                   # all tests
uv run pytest --cov --cov-report=term           # coverage
uv run pytest tests/test_llm.py                 # LLM checks only
LIVE_LLM_URL=http://localhost:8080 GEMINI_MODEL=gemini-3.5-flash GROQ_MODEL=openai/gpt-oss-120b \
  uv run pytest tests/test_llm.py -k live       # live LLM check through Bifrost
python3 ../scripts/smoke.py "<query>"           # end-to-end against a running stack
```

## Test plan

| Level | File | Tests | What is covered |
| --- | --- | --- | --- |
| Unit: tools and data | `test_core.py` | 34 | Query parsing, period parsing, all normalisers, catalog search and synonyms, vector search, MCP client, snapshot fallback, fail-fast embeddings |
| Unit: analytics accuracy | `test_analytics.py` | 10 | Hand-calculated per-cent change, sign-crossing change, Pearson r of ±1, minimum periods, cross-dataset alignment, fact list, Excel source |
| Data quality | `test_quality.py` | 15 | Duplicates, nulls, missing markers, required columns, outliers, coverage and stale-data notes, cleaning notes, every real snapshot, hierarchical CSV |
| LLM | `test_llm.py` | 23 | Hallucination detection, structured output, malformed output, revision loop, consistency, provider fallback config, live check |
| Integration: multi-agent | `test_agents.py` | 9 | Full graph with snapshots, cross-check planning, failed fetch, replan, revise, search outage, ambiguous query, invented plan keys |
| API | `test_api.py` | 9 | Health, validation (400, 404, 422), async job to completion, WebSocket replay of events and of failures, conversations and history |
| Performance and load | `test_performance.py` | 3 | 10,000-row normalise and summarise under 3 seconds, 40 concurrent API requests with p95 under 1 second |

Tests use a temporary SQLite database with foreign keys enforced (`conftest.py`), so persistence bugs that Postgres would reject also fail in tests. Government APIs, the MCP service and the LLM gateway are replaced with fakes at the module boundary, so the real parsing, normalising, statistics, graph routing and grounding code runs.

## LLM testing approach

### Hallucination detection

Every briefing passes through `check_grounding(text, facts)` before it is shown. The fact list contains every charted value, latest value, start value, change and correlation coefficient that the analytics step computed from the data. The check extracts every number from the briefing and insights and applies these rules:

| Rule | Example |
| --- | --- |
| Years and period labels are not claims | `2020`, `2024-Q3`, `2022-12` are ignored |
| Rounding must match the stated precision | `14%` matches 14.4, but `14.9%` does not match 14.4 |
| Unit scales are accepted | `187.3 thousand` and `0.19 million` match 187,300 |
| Unsigned numbers match by magnitude | "fell by 300" matches -300 |
| Numbers inside series labels are names | the 19 in "15 - 19 Years" is not a claim |
| Explicit signs must agree | `-2,700` does not match +2,700, including Unicode minus and hyphen variants |
| Ranges are not negatives | `10-15` and `157.6–180.3` read as two positive numbers |

A failed check triggers one revision where the model is told exactly which numbers were unsupported. If the revision still fails, the deterministic template briefing is used, and the UI shows the grounding status on every report. The sign rule was added after an end-to-end run where the model wrote "‑2,700" for a value of +2,700 and the magnitude-only check let it through. `test_wrong_sign_is_flagged` now covers that case.

The coordinator's planner is also checked: it may only return dataset keys from the candidate list, invented keys are dropped, and a plan with only invented keys is rejected (`test_coordinator_drops_keys_outside_candidates`).

### Accuracy validation

The numbers the LLM is allowed to use are produced by deterministic code, so accuracy is tested there with hand-calculated expectations: per-cent change of 200 to 250 is 25.0%, a series from 2,700 to -300 reports an absolute change of -3,000 rather than -111%, perfectly linear series give r = 1.0 and r = -1.0, and the real CSV snapshot yields 111.4 and 139.1 thousand ICT employed residents for 2020 and 2024.

### Consistency

- `test_summary_is_deterministic`: the same data always gives the same facts, charts and metrics.
- `test_same_answer_gives_the_same_report`: the same model answer always produces the same report and grounding result.
- `test_template_report_is_always_grounded`: the fallback path cannot fail its own check.
- The live test calls the real gateway twice with the same facts and requires both answers to pass grounding.
- The briefing chain runs at temperature 0.2 to reduce variation.

### Structured output and fallback

A LangChain `FakeListChatModel` replaces the gateway model, so the real prompt template and `PydanticOutputParser` run. Tests cover valid JSON, JSON inside a code fence, and non-JSON output (falls back to the template with `llm_error` set). `test_hallucinated_draft_is_revised_through_the_graph` drives the full LangGraph workflow with a planner answer, a hallucinated draft and a grounded revision, and checks that the final report is the grounded one. Provider fallback is verified by checking that the chat model sends `gemini/<model>` with `fallbacks: ["groq/<model>"]`, and that a single configured provider sends no fallback.

## End-to-end results

Run against the Docker stack with live government APIs and Bifrost, using `scripts/smoke.py`.

`scripts/smoke_all.py` runs the six README queries and prints a verdict for each.

| Scenario | Time | Outcome |
| --- | --- | --- |
| Analyse employment trends in the technology sector from 2020-2024 | 20 s | Two SingStat tables and the internal Excel source, 4 charts, 6 metrics, 5 correlations, grounding passed |
| How has CPI inflation changed since 2019 | 18 s | SingStat CPI plus a Data.gov.sg price index, grounding passed |
| How many total EP workers in Singapore from 2020 to current | 20 s | Data.gov.sg pass types plus SingStat population shares, note that data ends at 2022-12, grounding passed |
| HDB resale prices from 2015 to 2024 | 17 s | SingStat resale price index plus Data.gov.sg median prices, grounding passed |
| Births and fertility trends in Singapore | 24 s | SingStat and Data.gov.sg fertility series, grounding passed |
| tell me something | 34 s | Default datasets with an ambiguity note, grounding passed |
| gov-mcp stopped (outage) | 29 s | Search failure reported, three real snapshots loaded, note shown, grounding passed |

Issues found by these runs and fixed, each now covered by a unit test:

| Issue | Fix |
| --- | --- |
| Model wrote "‑2,700" for +2,700 and passed the magnitude-only check | Sign-aware grounding |
| Age bands like "15 - 19 Years" made even the template briefing fail grounding | Numbers in series labels are treated as names |
| Gemini embedding quota made search and fetch hang for over 2 minutes | Request-time embeddings fail fast with a cool-down |
| gov-mcp outage failed the whole analysis | The api loads pinned snapshots locally |
| Bundled snapshots were illustrative numbers cited as official | Replaced with real records captured from the live APIs |
| Hierarchical Data.gov.sg tables averaged age breakdowns into headline totals | Later sections are labelled separately |
| Seasonally adjusted and unadjusted variants reported as the top correlation | Variants of one series are skipped |
| Columns with "na" and "-" placeholders were rejected as non-numeric | Missing markers are ignored when detecting numeric columns |

Briefings used about 1,500 input and 1,200 output tokens, and the LLM call took 3 to 6 seconds. Token usage and latency are recorded on each report and shown in the Briefing tab.

## Performance

| Test | Budget | Measured |
| --- | --- | --- |
| Summarise 2 × 10,000 rows | 3 s | 0.2 s |
| Normalise 10,000 rows | 3 s | 0.07 s |
| 40 concurrent `POST /api/analyses` with stubbed agents | p95 under 1 s | 0.7 s for the whole batch |

Budgets are generous so CI runners do not flake, while still catching algorithmic regressions.

## Coverage

| Module | Coverage |
| --- | --- |
| `agents/analytics` | 99% |
| `agents/coordinator` | 97% |
| `agents/extractor` | 100% |
| `agents/pipeline` | 97% |
| `gov/data` | 96% |
| `main` (API) | 95% |
| `llm/client` | 90% |
| `core/store` | 77% |
| `gov/fetch` | 62% |
| `gov/catalog` | 56% |
| `gov/embed` | 47% |
| Total | 80% |

The lower figures are in live HTTP code paths (government APIs, embedding batch jobs, Postgres-only vector queries) that are exercised by the end-to-end runs rather than by unit tests.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to main and every pull request:

1. Backend: `uv sync`, then pytest with coverage and JUnit XML, uploaded as build artifacts.
2. Frontend: `npm ci`, typecheck and production build.
3. Images: `docker compose config` and `docker compose build` after both test jobs pass.
