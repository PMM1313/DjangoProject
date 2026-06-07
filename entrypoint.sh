#!/bin/sh

echo "Waiting for database infrastructure..."
sleep 3

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting production WSGI server via Gunicorn..."
exec gunicorn Server.wsgi:application --bind 0.0.0.0:8000 --workers 3