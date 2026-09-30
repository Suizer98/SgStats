FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/uv.lock* ./
RUN uv sync --no-dev
COPY backend/app ./app
COPY backend/data ./data
COPY mcp/server.py ./server.py
COPY mcp/tools.py ./tools.py
ENV PYTHONPATH=/app
EXPOSE 8100
CMD ["uv", "run", "--no-dev", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
