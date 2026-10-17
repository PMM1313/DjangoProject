import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Server.settings")

import django
from django.db import connections
from django.db.utils import OperationalError


print("=== Python import diagnostics ===", flush=True)
print("Working directory:", os.getcwd(), flush=True)
print("Python executable:", sys.executable, flush=True)
print("Python path:", sys.path, flush=True)
print("Server directory exists:", os.path.isdir("/app/Server"), flush=True)
print("Server init exists:", os.path.isfile("/app/Server/__init__.py"), flush=True)
print("Settings exists:", os.path.isfile("/app/Server/settings.py"), flush=True)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Server.settings")

MAX_ATTEMPTS = 30
RETRY_DELAY = 2


def main():
    django.setup()
    db = connections["default"]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            db.ensure_connection()
            with db.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            print("Database is ready.")
            return

        except OperationalError as exc:
            print(
                f"Database not ready "
                f"({attempt}/{MAX_ATTEMPTS}): {exc}",
                flush=True,
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    print("Database did not become ready in time.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
