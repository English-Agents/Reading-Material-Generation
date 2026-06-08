#!/usr/bin/env bash
set -e

# Render provides DATABASE_URL as postgresql:// or postgres://
# SQLAlchemy asyncpg needs postgresql+asyncpg://
if [[ "$DATABASE_URL" == postgres://* ]]; then
  export DATABASE_URL="${DATABASE_URL/postgres:\/\//postgresql+asyncpg://}"
elif [[ "$DATABASE_URL" == postgresql://* && "$DATABASE_URL" != *"+asyncpg"* ]]; then
  export DATABASE_URL="${DATABASE_URL/postgresql:\/\//postgresql+asyncpg://}"
fi

echo "Running Alembic migrations..."
alembic upgrade head

echo "Seeding prompt versions (idempotent)..."
python seed_db.py

echo "Starting server on port ${PORT:-8000}..."
exec uvicorn ppt_agent.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
