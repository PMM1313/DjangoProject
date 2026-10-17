#!/bin/sh
set -e # stop execution if something doesnt start

# Check what argument is passed from Coolify (defaults to 'web' if nothing is passed)
COMMAND="${1:-web}"

case "$COMMAND" in
  web)
    echo "Waiting for database..."
    python scripts/wait_for_db.py

    echo "Running database migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput

    echo "Starting production WSGI server via Gunicorn..."
    exec python -m gunicorn Server.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 2 \
        --threads 4 \
        --worker-class gthread \
        --max-requests 200 \
        --max-requests-jitter 20 \
        --timeout 30
    ;;

  worker)
    echo "Waiting for database..."
    python scripts/wait_for_db.py

    echo "Waiting for Redis..."
    python scripts/wait_for_redis.py

    echo "Starting Celery Worker..."
    exec python -m celery -A Server worker --loglevel=info --concurrency=1
    ;;

  beat)
    echo "Waiting for database..."
    python scripts/wait_for_db.py

    echo "Waiting for Redis..."
    python scripts/wait_for_redis.py

    echo "Starting Celery Beat..."
    exec python -m celery -A Server beat --loglevel=info
    ;;

  *)
    echo "Executing custom command: $@"
    exec "$@"
    ;;
esac