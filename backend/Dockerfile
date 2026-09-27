FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
COPY uv.lock* ./
RUN uv sync --no-dev
COPY app ./app
COPY data ./data
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
