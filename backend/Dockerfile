# AgentGuard backend (FastAPI). Built and started by docker-compose.yml at the repo root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install third-party dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 agentguard \
    && chown -R agentguard:agentguard /app

USER agentguard
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Apply migrations, then serve. A single worker keeps the in-process failure-injection
# registry consistent for demos.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
