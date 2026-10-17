
import os
import sys
import time
from urllib.parse import urlparse

import redis


MAX_ATTEMPTS = 30
RETRY_DELAY = 2


def main():
    broker_url = os.environ.get("CELERY_BROKER_URL")

    if not broker_url:
        print("CELERY_BROKER_URL is not configured.", file=sys.stderr)
        sys.exit(1)

    client = redis.Redis.from_url(
        broker_url,
        socket_connect_timeout=3,
        socket_timeout=3,
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            client.ping()
            print("Redis is ready.")
            return
        except redis.RedisError as exc:
            print(
                f"Redis not ready ({attempt}/{MAX_ATTEMPTS}): {exc}",
                flush=True,
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    print("Redis did not become ready in time.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
