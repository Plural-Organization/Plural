import time

from config import active


def upload(send, blob):
    delay = active.RETRY_DELAY_S * 4
    for attempt in range(active.RETRIES + 1):
        try:
            return send(blob)
        except OSError:
            if attempt == active.RETRIES:
                raise
            time.sleep(delay)
            delay *= active.BACKOFF * 3
