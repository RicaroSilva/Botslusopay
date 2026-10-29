# LUSOPAY Bot Manager — runner de fluxos nativos (Linux; sem taskt/OpenBots)
# Contexto de build: raiz do repositório.
FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10002 --home /app runner
# Java 21 (Eclipse Temurin) para os robôs Groovy: o isolamento usa o SecurityManager, que deixa de existir no Java 24
COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
WORKDIR /app
COPY worker/pyproject.toml worker/
COPY worker/lusopay_worker worker/lusopay_worker
# [sql] instala o pymssql (SQL Server) — wheels pré-compiladas, sem driver ODBC
RUN pip install "./worker[sql]"
# Groovy descarregado do Maven Central com o SHA-256 verificado
ENV WORKER_GROOVY_LIB=/opt/groovy
RUN python -m lusopay_worker.groovy setup
USER runner
ENV WORKER_ADAPTERS=flow \
    WORKER_STATE_FILE=/tmp/worker-state.json \
    WORKER_POLL_SECONDS=3 \
    WORKER_HEARTBEAT_SECONDS=10
CMD ["python", "-m", "lusopay_worker.main"]
