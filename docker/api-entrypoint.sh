#!/bin/sh
# api       → aplica migrações e arranca a API
# scheduler → arranca o scheduler (agendamentos, polling, recolha de execuções perdidas)
# outro     → executa o comando indicado (ex.: python -m botmanager.cli create-user ...)
set -e
case "$1" in
  api)
    alembic upgrade head
    exec uvicorn --factory botmanager.main:create_app --host 0.0.0.0 --port 8000 \
      --proxy-headers --forwarded-allow-ips="${BM_FORWARDED_ALLOW_IPS:-127.0.0.1}"
    ;;
  scheduler)
    exec python -m botmanager.scheduler
    ;;
  *)
    exec "$@"
    ;;
esac
