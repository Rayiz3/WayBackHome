"""Worker orchestration. Provider must perform a live, complete query."""
from datetime import datetime, timezone, timedelta
import time
from server.monitor import decode_watch

KST = timezone(timedelta(hours=9))


class Worker:
    def __init__(self, store, provider, transport, clock=time.time):
        self.store, self.provider, self.transport, self.clock = store, provider, transport, clock

    def tick(self):
        now = self.clock()
        self.store.heartbeat(now)
        for row in self.store.due(now):
            self.store.heartbeat(self.clock())
            watch = decode_watch(row["config"])
            if datetime.combine(watch.day,watch.end,tzinfo=KST).timestamp() < now:
                self.store.expire(row["id"],row["revision"])
                continue
            try:
                observation = self.provider.query(watch)
                self.store.observe(row["id"],row["revision"],observation,self.clock())
            except Exception:
                # Do not turn a timeout, queue, login, or parser failure into "sold out".
                self.store.query_failed(row["id"],row["revision"],self.clock())
            self.drain()
        self.drain()
        self.store.receipts(self.transport,self.clock())
        self.store.heartbeat(self.clock())

    def drain(self):
        # Bound each tick so an unexpected queue cannot monopolize the worker.
        for _ in range(100):
            if self.store.deliver_one(self.transport,self.clock()) is None:
                break

    def run(self, stop):
        while not stop.is_set():
            self.tick()
            stop.wait(5)
