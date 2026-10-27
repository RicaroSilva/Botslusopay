# LUSOPAY Bot Manager — imagem da API web (também usada pelo scheduler)
# Contexto de build: raiz do repositório.

# 1) compilar o frontend
FROM node:20-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) backend Python
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --uid 10001 --home /app botmanager
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/botmanager backend/botmanager
RUN pip install ./backend
COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/
COPY bots/registry bots/registry
COPY --from=frontend /src/frontend/dist frontend/dist
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh
RUN chmod 0755 /usr/local/bin/api-entrypoint.sh && chown -R botmanager /app
USER botmanager
WORKDIR /app/backend
ENV BM_REGISTRY_DIR=/app/bots/registry
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
ENTRYPOINT ["api-entrypoint.sh"]
CMD ["api"]
