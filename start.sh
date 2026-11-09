#!/usr/bin/env sh
# Render start command: apply migrations, then serve on the port Render provides.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
