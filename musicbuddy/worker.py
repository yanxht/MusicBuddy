"""Queue worker: processes lesson jobs enqueued by the folder watcher or the web upload."""
import json
import logging
import threading

from . import config, storage
from .pipeline import run

log = logging.getLogger(__name__)
VISIBILITY_S = 3600


def handle(msg) -> None:
    body = json.loads(msg.content)
    date = body["date"]
    status = storage.get_json(config.DATA_CONTAINER, f"{date}/status.json") or {}
    if status.get("state") == "ready" and status.get("updated", "") > msg.inserted_on.isoformat():
        log.info("skip %s: already processed after this job was queued", date)
        return
    run.process(date)


def loop(stop: threading.Event | None = None, poll_s: int = 20) -> None:
    stop = stop or threading.Event()
    q = storage.queue()
    log.info("worker listening on queue '%s'", config.JOB_QUEUE)
    while not stop.is_set():
        try:
            msgs = list(q.receive_messages(max_messages=1, visibility_timeout=VISIBILITY_S))
        except Exception:  # noqa: BLE001 - transient storage errors: back off and retry
            log.exception("queue receive failed")
            stop.wait(60)
            continue
        if not msgs:
            stop.wait(poll_s)
            continue
        msg = msgs[0]
        try:
            handle(msg)
            q.delete_message(msg)
        except Exception:  # noqa: BLE001
            log.exception("job failed (attempt %s): %s", msg.dequeue_count, msg.content)
            if msg.dequeue_count >= 3:
                q.delete_message(msg)


def start_background() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), daemon=True, name="lesson-worker").start()
    return stop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    loop()
