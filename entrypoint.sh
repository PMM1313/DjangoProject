#!/bin/sh
set -e # stop execution if something doesnt start

# Wait briefly for infrastructure services
echo "Waiting for database infrastructure..."
sleep 3

# Check what argument is passed from Coolify (defaults to 'web' if nothing is passed)
COMMAND="${1:-web}"

case "$COMMAND" in
  web)
    echo "Running web tasks..."
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput

    echo "Starting production WSGI server via Gunicorn..."
    exec gunicorn Server.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 2 \
        --threads 4 \
        --worker-class gthread \
        --max-requests 200 \
        --max-requests-jitter 20 \
        --timeout 30
    ;;

  worker)
    echo "Starting Celery Worker..."
    exec celery -A Server worker --loglevel=info
    ;;

  beat)
    echo "Starting Celery Beat..."
    exec celery -A Server beat --loglevel=info
    ;;

  *)
    echo "Executing custom command: $@"
    exec "$@"
    ;;
esac