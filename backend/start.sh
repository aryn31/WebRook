#!/bin/sh
# Runs the API, the worker and the scheduler (beat) in one container, for single-service hosting such as
# Render's free plan. If any of them stops, the container exits so the host restarts it.
set -e

# Update the database tables
alembic upgrade head

# Worker with beat built in (-B). Run exactly one copy of this container, or beat schedules everything twice.
celery -A app.worker.celery_app worker -B --loglevel=INFO --concurrency=2 --schedule=/tmp/celerybeat-schedule &
WORKER=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers &
API=$!

# Pass a stop signal from the host on to both processes.
trap 'kill -TERM "$WORKER" "$API" 2>/dev/null' TERM INT

set +e
while kill -0 "$WORKER" 2>/dev/null && kill -0 "$API" 2>/dev/null; do
  sleep 5
done

echo "start.sh: a process stopped; shutting down so the container restarts" >&2
kill -TERM "$WORKER" "$API" 2>/dev/null
wait
exit 1
