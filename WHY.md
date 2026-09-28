# Why these choices

## Frontend

I used React with TypeScript instead of Next.js. This proof of concept does not need server-side rendering. Vite is enough to build the page and talk to the API.

I used Chakra UI because I had been trying to line this up with FormSG, the Open Government Products form builder, and that product uses Chakra. Matching that style made the screens feel closer to an existing government tool.

I used Zustand instead of Redux because it was quicker to learn. One store holds the query, the live agent events and the result. The API returns the chart series, and the page can switch the same data between line, area and bar without another call.

I used WebSocket because an analysis can take time and I wanted to stream the agent activity while it runs. The events are also stored, so reconnecting to the same analysis replays the earlier steps before continuing with live updates.

## Backend

I chose LangChain because it is mature and has been used in many real-world scenarios. It gave me prompt templates, model calls and structured output without having to build that plumbing myself. LangGraph then made it straightforward to connect the workflow as nodes, including the replan and revise paths.

Pydantic helps firm up the model output. The planner, intent router, chat reply and briefing all have schemas. If a response does not match, the code falls back to search ranking, a keyword decision or a local report instead of passing bad output through the graph.

I also considered Google ADK 2.0, especially for testing nodes separately. For this proof of concept, LangChain and LangGraph were faster to put together. I kept the model client, agent prompts and graph separate, so another agent can be added later as a new node without rewriting the core.

I also added a general agent for ordinary chat. A follow-up that asks to change the result does not go there: it edits the analysis already saved in the thread.

## Multi-agent design

I split the work into four agents instead of one prompt that searches, fetches and writes. The coordinator chooses datasets. The extractor fetches and cleans them. The analytics agent computes the figures and drafts the briefing. The general agent handles chat. LangGraph is the only place that decides who runs next, so an agent does not call the others itself.

A new question is classified first. Chat goes straight to the general agent. A statistics question goes coordinator, then extractor, then analytics. If the fetch returns nothing usable, the graph replans once with the remaining candidates. If the briefing contains a number that is not in the computed facts, it revises once and otherwise falls back to a template. Each step emits a thought, an action and an observation, which is what the activity panel streams.

A follow-up in a thread that already has an analysis does not start that search again. A change request reuses the saved datasets and reruns analytics for the new wording. A chat message stays with the general agent and answers from that same result. A different topic needs a new conversation.

## MCP server

I separated government data access from LangChain because the tools should not belong to one agent framework. `gov-mcp` exposes `search_datasets` and `fetch_dataset` over HTTP, so another LangChain, ADK or other agent service could reuse the same interface.

It also keeps Data.gov.sg, SingStat, Excel parsing, normalisation and quality checks away from the agents. If an upstream API changes, I can fix the MCP service without changing the graph or its prompts.

The current version validates arguments and only exposes two tools, but it does not have authentication yet. In production, MCP could become the gateway that controls which users or agents may access each dataset, applies rate limits and masking, and records an audit trail. The agent server should then have no direct route to protected APIs, so those controls cannot be bypassed.

## Bifrost

I wanted to integrate different LLM providers behind one OpenAI-compatible API. Bifrost connects Gemini and Groq, handles the fallback order, and keeps provider-specific setup outside the Python application.

Because of that, the LangChain backend only needs one `ChatOpenAI` module in `app/llm/client.py`. The agents all use the same client instead of having separate Gemini and Groq integrations. This keeps the code simpler and makes provider changes easier to maintain.

This setup only uses the shared API and the Gemini-to-Groq fallback. Logging is off in the current config. Later I would turn on request logs for tokens, cost and latency, then add semantic caching, budgets, rate limits and virtual keys so each caller only reaches the models it is allowed to use.

## Postgres

Postgres is the store for analyses and also for the embeddings, through the pgvector plugin. Each dataset fetched from the MCP service is saved with its title, agency and series labels, plus a vector from `gemini-embedding-2`. That model is on the free tier and the column is 768 dimensions, matching `EMBED_DIM` in `app/gov/embed.py`.

Search uses exact cosine distance. I did not add an HNSW index because the table is still small, and comparing the query with every stored vector is accurate enough. HNSW would only start to matter once a full scan gets slow.

If that table gets heavy, I would put Redis in front of it. Postgres stays the source of the embeddings. Redis caches the hot queries, so a repeated question does not embed the text again or scan Postgres every time. That cuts both latency and embedding calls. If the vector table itself keeps growing, I would add an HNSW index in pgvector for the large scan, and still leave Redis for the queries people ask often.

## Docker

The API and MCP images use `python:3.12-slim`, while the frontend uses `node:22-alpine`. I chose the language images instead of a full Ubuntu base so the images stay smaller. That uses less container registry space and makes pulls and deployments faster.

There are two named volumes for now: `pgdata` keeps the database between restarts, and `web_node_modules` avoids reinstalling frontend packages during local rebuilds. Postgres should be backed up with `pg_dump` rather than by copying a live volume. The frontend and Bifrost folders are bind mounts for development and configuration, not named data volumes.

Ideally for compose should use `docker compose up -d --build` when dependencies changes are included. In production I would build once in CI, tag the image with a commit or version, and deploy that exact image. Rebuilding separately on every server could produce different images, so a versioned immutable image is safer than relying on `--build` there.

## CI

For this proof of concept, Docker Compose is enough for in-house testing. Bare metal or a lift-and-shift VM does not matter. If Docker is installed, the same compose file can run there.

The current pipeline is GitHub Actions. It runs the backend tests, the frontend typecheck and build, then `docker compose build`. The same checks can run inside the image, with the source copied in, and that is also where I would add SAST. Because the app is already containerised, that pipeline can sit on GitHub, GitLab or Azure DevOps.

I am not worried about hosting on Azure or AWS. The harder case is an air-gapped Singapore GCC environment, or on-prem next to it. There the images cannot be pulled from the public internet, so Docker itself has to be hardened: a private registry, scanned images, and no runtime install of packages from outside.
