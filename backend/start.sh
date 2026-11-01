#!/bin/sh
set -e

# Update the database tables
alembic upgrade head

# Worker with beat built in, running in the background
celery -A app.worker.celery_app worker -B --loglevel=INFO --concurrency=2 --schedule=/tmp/celerybeat-schedule &

# API in the foreground
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
