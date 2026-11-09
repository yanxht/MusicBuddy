import json
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from musicbuddy import worker


class FakeQueue:
    def __init__(self, msg):
        self.msgs = [msg]
        self.updates, self.deleted = [], []

    def receive_messages(self, **_):
        return [self.msgs.pop()] if self.msgs else []

    def update_message(self, mid, receipt, visibility_timeout):
        self.updates.append(receipt)
        return SimpleNamespace(pop_receipt=f"r{len(self.updates)}")

    def delete_message(self, mid, receipt):
        self.deleted.append((mid, receipt))


def run_once(monkeypatch, handle, dequeue_count=1):
    msg = SimpleNamespace(id="m1", pop_receipt="r0", dequeue_count=dequeue_count,
                          content=json.dumps({"date": "20261107"}), inserted_on=datetime.now(timezone.utc))
    q = FakeQueue(msg)
    stop = threading.Event()
    monkeypatch.setattr(worker.storage, "queue", lambda: q)
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.05)

    def fake_handle(m):
        try:
            handle(m)
        finally:
            stop.set()

    monkeypatch.setattr(worker, "handle", fake_handle)
    worker.loop(stop, poll_s=0)
    return q


def test_lease_renewed_and_deleted_with_latest_receipt(monkeypatch):
    q = run_once(monkeypatch, lambda m: time.sleep(0.3))
    assert q.updates and q.updates[0] == "r0"
    assert q.deleted == [("m1", f"r{len(q.updates)}")]


def test_failed_job_kept_until_third_attempt(monkeypatch):
    def boom(_):
        raise RuntimeError("x")

    assert run_once(monkeypatch, boom).deleted == []
    assert run_once(monkeypatch, boom, dequeue_count=3).deleted == [("m1", "r0")]
