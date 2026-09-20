"""Durable watch and delivery state for the single-user monitoring service.

A successful Expo ticket, provider receipt, and device acknowledgement are separate
states. A worker must supply a fresh, fully validated query result to create alerts.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, time
import hashlib
import json
import sqlite3
import time as clock
import uuid

from server.seat_alerts import Watch, Train, matching_trains, send_alert, check_receipt, PushError


def watch_json(watch):
    data = asdict(watch)
    data.update(day=watch.day.isoformat(), start=watch.start.isoformat(), end=watch.end.isoformat())
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def decode_watch(raw):
    data = json.loads(raw)
    return Watch(date.fromisoformat(data["day"]), data["departure"], data["arrival"],
                 time.fromisoformat(data["start"]), time.fromisoformat(data["end"]),
                 tuple(data["classes"]), tuple(data["train_numbers"]), data["adults"])


def encode_trains(trains):
    return json.dumps([{**asdict(t), "start": t.start.isoformat(), "end": t.end.isoformat()} for t in trains])


def decode_trains(raw):
    return [Train(**{**v, "start": time.fromisoformat(v["start"]), "end": time.fromisoformat(v["end"])})
            for v in json.loads(raw)]


@dataclass(frozen=True)
class Observation:
    watch: Watch
    trains: tuple[Train, ...]
    observed_at: float
    status: str = "ok"  # ok, no_trains, error, waiting; never infer sold_out from empty HTML.


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS service_state (key TEXT PRIMARY KEY, value REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS watches (
                    id TEXT PRIMARY KEY, config TEXT NOT NULL, token TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'pending', checked_at REAL,
                    error TEXT, next_check REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id),
                    revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, trains TEXT NOT NULL,
                    observed_at REAL NOT NULL, created_at REAL NOT NULL,
                    state TEXT NOT NULL, ticket TEXT, error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                    received_at REAL,
                    UNIQUE(watch_id, revision, fingerprint)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, watch_id, watch, token):
        import re
        if not watch_id or len(watch_id) > 128:
            raise ValueError("Invalid watch ID")
        if not re.fullmatch(r"(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]", token):
            raise ValueError("Invalid push token")
        config = watch_json(watch)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
            if old and old["config"] == config and old["token"] == token:
                db.execute("UPDATE watches SET enabled=1,next_check=0 WHERE id=?", (watch_id,))
            elif old:
                db.execute("""UPDATE watches SET config=?,token=?,revision=revision+1,enabled=1,
                              status='pending',error=NULL,next_check=0 WHERE id=?""", (config,token,watch_id))
                db.execute("UPDATE alerts SET state='cancelled' WHERE watch_id=? AND state IN ('queued','retry')", (watch_id,))
            else:
                db.execute("INSERT INTO watches(id,config,token) VALUES(?,?,?)", (watch_id,config,token))

    def stop(self, watch_id):
        with self.connect() as db:
            db.execute("UPDATE watches SET enabled=0,status='stopped' WHERE id=?", (watch_id,))
            db.execute("UPDATE alerts SET state='cancelled' WHERE watch_id=? AND state IN ('queued','retry')", (watch_id,))

    def get(self, watch_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
        return dict(row) if row else None

    def due(self, now):
        with self.connect() as db:
            return [dict(v) for v in db.execute("SELECT * FROM watches WHERE enabled=1 AND next_check<=?", (now,))]

    def heartbeat(self, now):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO service_state(key,value) VALUES('worker',?)", (now,))

    def worker_live(self, now=None):
        now = clock.time() if now is None else now
        with self.connect() as db:
            row = db.execute("SELECT value FROM service_state WHERE key='worker'").fetchone()
        return bool(row and 0 <= now - row["value"] < 180)

    def query_failed(self, watch_id, revision, now):
        with self.connect() as db:
            db.execute("""UPDATE watches SET status='error',error='QUERY_FAILED',checked_at=?,next_check=?
                          WHERE id=? AND revision=? AND enabled=1""", (now,now+300,watch_id,revision))

    def expire(self, watch_id, revision):
        with self.connect() as db:
            db.execute("""UPDATE watches SET enabled=0,status='expired'
                          WHERE id=? AND revision=?""", (watch_id,revision))
            db.execute("""UPDATE alerts SET state='cancelled' WHERE watch_id=? AND revision=?
                          AND state IN ('queued','retry')""", (watch_id,revision))

    def observe(self, watch_id, revision, result, now=None):
        now = clock.time() if now is None else now
        if not 0 <= now - result.observed_at <= 120:
            raise ValueError("Stale or future observation")
        if result.status not in {"ok", "no_trains", "error", "waiting"}:
            raise ValueError("Unknown query status")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
            if not row or not row["enabled"] or row["revision"] != revision:
                return None
            watch = decode_watch(row["config"])
            if watch != result.watch:
                raise ValueError("Observed query does not match saved conditions")
            if result.status != "ok":
                if result.trains:
                    raise ValueError("Non-success observation contains train data")
                db.execute("UPDATE watches SET status=?,checked_at=?,next_check=? WHERE id=?",
                           (result.status, now, now + 300, watch_id))
                return None
            if not result.trains:
                raise ValueError("An empty success is ambiguous; classify it explicitly")
            matches = matching_trains(watch, watch.day, result.trains)
            unknown = any(getattr(t, s) == "unknown" for t in result.trains for s in watch.classes)
            status = "available" if matches else "unknown" if unknown else "no_matching_seats"
            db.execute("UPDATE watches SET status=?,checked_at=?,error=NULL,next_check=? WHERE id=?",
                       (status, now, now + 300, watch_id))
            if not matches:
                return None
            # Preserve dedup across legacy per-seat alerts and grouped alerts.
            seen = set()
            for previous in db.execute("""SELECT trains FROM alerts WHERE watch_id=? AND revision=?
                                        AND state NOT IN ('expired','cancelled')""", (watch_id, revision)):
                for train in decode_trains(previous["trains"]):
                    for seat in watch.classes:
                        if getattr(train, seat) == "available":
                            seen.add((train.number, train.start.isoformat(), seat))
            matches = sorted({(t.number, t.start): t for t in matches}.values(),
                             key=lambda t: (t.start, t.number))
            current = {(t.number, t.start.isoformat(), seat) for t in matches
                       for seat in watch.classes if getattr(t, seat) == "available"}
            unseen = current - seen
            if not unseen:
                return []
            fingerprint = hashlib.sha256(json.dumps(sorted(unseen)).encode()).hexdigest()
            alert_id = str(uuid.uuid4())
            db.execute("""INSERT INTO alerts(id,watch_id,revision,fingerprint,trains,observed_at,created_at,state)
                          VALUES(?,?,?,?,?,?,?,'queued')""",
                       (alert_id,watch_id,revision,fingerprint,encode_trains(matches),result.observed_at,now))
            return [alert_id]

    def deliver_one(self, transport, now=None):
        now = clock.time() if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT a.*,w.config,w.token FROM alerts a JOIN watches w ON a.watch_id=w.id
                WHERE a.state IN ('queued','retry') AND a.next_attempt<=? AND w.enabled=1
                AND a.revision=w.revision ORDER BY a.created_at LIMIT 1""", (now,)).fetchone()
            if not row:
                return None
            if now - row["observed_at"] > 120:
                db.execute("UPDATE alerts SET state='expired' WHERE id=?", (row["id"],))
                # Remove dedup claim: the next fresh observation may notify again.
                db.execute("UPDATE alerts SET fingerprint=fingerprint || ':' || id WHERE id=?", (row["id"],))
                return "expired"
            db.execute("UPDATE alerts SET state='sending',attempts=attempts+1 WHERE id=?", (row["id"],))
        try:
            ticket = send_alert(row["token"], decode_watch(row["config"]), decode_trains(row["trains"]),
                                row["id"], transport)
        except PushError as error:
            state = "retry" if error.retryable and row["attempts"] < 3 else "failed"
            with self.connect() as db:
                db.execute("UPDATE alerts SET state=?,error=?,next_attempt=? WHERE id=?",
                           (state,error.code,now + min(60, 5 * 2 ** row["attempts"]),row["id"]))
                if error.code == "DeviceNotRegistered":
                    db.execute("UPDATE watches SET enabled=0,status='device_unregistered',error=? WHERE token=?",
                               (error.code,row["token"]))
            return state
        except Exception:
            # Unknown transport outcome: never automatically resend as if nothing happened.
            with self.connect() as db:
                db.execute("UPDATE alerts SET state='uncertain',error='UNKNOWN_SEND_OUTCOME' WHERE id=?", (row["id"],))
            raise
        with self.connect() as db:
            db.execute("UPDATE alerts SET state='ticket_accepted',ticket=?,error=NULL,next_attempt=? WHERE id=? AND received_at IS NULL",
                       (ticket,now + 30,row["id"]))
        return "ticket_accepted"

    def receipts(self, transport, now=None):
        now = clock.time() if now is None else now
        with self.connect() as db:
            rows = db.execute("SELECT * FROM alerts WHERE state='ticket_accepted' AND next_attempt<=?", (now,)).fetchall()
        for row in rows:
            try:
                state = check_receipt(row["ticket"], transport)
                if state == "pending":
                    state = "receipt_missing" if now - row["created_at"] > 900 else "ticket_accepted"
                error = None
            except PushError as exc:
                state, error = ("ticket_accepted" if exc.retryable else "failed"), exc.code
            with self.connect() as db:
                # Do not downgrade a phone acknowledgement that arrived during the request.
                db.execute("UPDATE alerts SET state=?,error=?,next_attempt=? WHERE id=? AND received_at IS NULL",
                           (state,error,now + 30,row["id"]))
                if error == "DeviceNotRegistered":
                    db.execute("""UPDATE watches SET enabled=0,status='device_unregistered' WHERE token=
                                  (SELECT token FROM watches WHERE id=?)""", (row["watch_id"],))

    def acknowledge(self, alert_id, now=None):
        now = clock.time() if now is None else now
        with self.connect() as db:
            row = db.execute("SELECT state FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if not row or row['state'] not in {'sending', 'uncertain', 'ticket_accepted', 'provider_accepted', 'receipt_missing', 'device_received'}:
                raise ValueError("Alert has not been sent")
            db.execute("UPDATE alerts SET state='device_received',received_at=COALESCE(received_at,?) WHERE id=?", (now,alert_id))

    def alerts(self, watch_id):
        with self.connect() as db:
            return [dict(v) for v in db.execute(
                "SELECT id,state,error,created_at,received_at FROM alerts WHERE watch_id=? ORDER BY created_at DESC", (watch_id,))]
