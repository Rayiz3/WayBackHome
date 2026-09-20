import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from server.monitor import Store, Observation
from server.worker import Worker
from server.seat_alerts import parse_cards
from server.tests.test_seat_alerts import WATCH, CARD

class WorkerTests(unittest.TestCase):
    def test_two_watches_query_error_isolated_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/"db")
            watch = replace(WATCH,classes=("standard",))
            store.put("a",watch,"ExpoPushToken[test]")
            store.put("b",replace(watch,arrival="서울"),"ExpoPushToken[test]")
            now = datetime(2026,9,17,tzinfo=timezone.utc).timestamp()
            class Provider:
                def query(self,w):
                    if w.arrival == "서울":
                        raise TimeoutError()
                    return Observation(w,tuple(parse_cards(CARD)),now)
            calls=[]
            def transport(endpoint,payload):
                calls.append(endpoint)
                return {"data":{"status":"ok","id":"ticket"}}
            worker = Worker(store,Provider(),transport,lambda:now)
            worker.tick()
            worker.tick()
            self.assertEqual(calls,["send"])
            self.assertEqual(store.get("a")["status"],"available")
            self.assertEqual(store.get("b")["status"],"error")
            self.assertEqual(store.alerts("a")[0]["state"],"ticket_accepted")

    def test_departed_watch_never_queries_or_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/"db")
            store.put("a",WATCH,"ExpoPushToken[test]")
            class Provider:
                def query(self,w): raise AssertionError("Expired query")
            worker=Worker(store,Provider(),lambda *_: self.fail("Expired push"),
                          lambda:datetime(2026,10,8,tzinfo=timezone.utc).timestamp())
            worker.tick()
            self.assertEqual(store.get("a")["status"],"expired")

if __name__ == "__main__":
    unittest.main()

