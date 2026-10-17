
import sys
import time

import django
from django.db import connections
from django.db.utils import OperationalError


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
