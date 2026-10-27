# LUSOPAY Bot Manager — runner de fluxos nativos (Linux; sem taskt/OpenBots)
# Contexto de build: raiz do repositório.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10002 --home /app runner
WORKDIR /app
COPY worker/pyproject.toml worker/
COPY worker/lusopay_worker worker/lusopay_worker
# [sql] instala o pymssql (SQL Server) — wheels pré-compiladas, sem driver ODBC
RUN pip install "./worker[sql]"
USER runner
ENV WORKER_ADAPTERS=flow \
    WORKER_STATE_FILE=/tmp/worker-state.json \
    WORKER_POLL_SECONDS=3 \
    WORKER_HEARTBEAT_SECONDS=10
CMD ["python", "-m", "lusopay_worker.main"]
