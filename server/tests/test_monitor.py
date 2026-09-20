import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from server.monitor import Store, Observation
from server.seat_alerts import parse_cards, PushError
from server.tests.test_seat_alerts import WATCH, CARD

TOKEN = "ExpoPushToken[test]"

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "monitor.db"
        self.store = Store(self.path)
        self.watch = replace(WATCH, classes=("standard",))
        self.store.put("w1", self.watch, TOKEN)
        self.result = Observation(self.watch, tuple(parse_cards(CARD)), 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_restart_dedup_and_no_duplicate_registration(self):
        ids = self.store.observe("w1", 1, self.result, 1000)
        self.assertEqual(len(ids), 1)
        restarted = Store(self.path)
        restarted.put("w1", self.watch, TOKEN)
        self.assertEqual(restarted.get("w1")["revision"], 1)
        self.assertEqual(restarted.observe("w1", 1, self.result, 1001), [])

    def test_changed_conditions_and_stop_discard_old_result(self):
        self.store.put("w1", replace(self.watch, arrival="서울"), TOKEN)
        self.assertIsNone(self.store.observe("w1", 1, self.result, 1000))
        self.store.stop("w1")
        self.assertIsNone(self.store.observe("w1", 2, self.result, 1000))
        self.assertFalse(self.store.due(1001))

    def test_stale_empty_wrong_query_never_notifies(self):
        for result in [replace(self.result, observed_at=800), replace(self.result,trains=()),
                       replace(self.result,watch=replace(self.watch,arrival="서울"))]:
            with self.assertRaises(ValueError):
                self.store.observe("w1",1,result,1000)
        self.store.observe("w1",1,replace(self.result,status="error",trains=()),1000)
        self.assertEqual(self.store.get("w1")["status"],"error")
        self.assertEqual(self.store.alerts("w1"),[])

    def test_send_provider_receipt_and_device_ack_are_distinct(self):
        ids = self.store.observe("w1",1,self.result,1000)
        def send(*_): return {"data":{"status":"ok","id":"ticket"}}
        self.assertEqual(self.store.deliver_one(send,1001),"ticket_accepted")
        self.assertIsNone(self.store.deliver_one(send,1002))
        self.store.receipts(lambda *_: {"data":{"ticket":{"status":"ok"}}},1032)
        self.assertEqual(self.store.alerts("w1")[0]["state"],"provider_accepted")
        self.store.acknowledge(ids[0],1033)
        self.assertEqual(self.store.alerts("w1")[0]["state"],"device_received")

    def test_retry_backoff_and_disabled_device(self):
        self.store.observe("w1",1,self.result,1000)
        def transient(*_): raise PushError("HTTP_503",True)
        self.assertEqual(self.store.deliver_one(transient,1001),"retry")
        self.assertIsNone(self.store.deliver_one(transient,1002))
        def permanent(*_): raise PushError("DeviceNotRegistered")
        self.assertEqual(self.store.deliver_one(permanent,1007),"failed")
        self.assertEqual(self.store.get("w1")["status"],"device_unregistered")
        self.assertEqual(self.store.get("w1")["enabled"],0)

    def test_expired_delivery_requires_new_observation(self):
        self.store.observe("w1",1,self.result,1000)
        self.assertEqual(self.store.deliver_one(lambda *_: self.fail("Stale seat sent"),1121),"expired")
        self.assertEqual(len(self.store.observe("w1",1,replace(self.result,observed_at=1122),1122)),1)

    def test_phone_ack_during_network_response_not_overwritten(self):
        ids = self.store.observe("w1",1,self.result,1000)
        def transport(*_):
            self.store.acknowledge(ids[0],1002)
            return {"data":{"status":"ok","id":"ticket"}}
        self.store.deliver_one(transport,1001)
        self.assertEqual(self.store.alerts("w1")[0]["state"],"device_received")

    def test_ack_before_send_rejected(self):
        ids = self.store.observe("w1",1,self.result,1000)
        with self.assertRaises(ValueError):
            self.store.acknowledge(ids[0],1001)

    def test_grouped_push_counts_trains_and_preserves_dedup(self):
        watch = replace(self.watch, classes=('standard','first'))
        self.store.put('both', watch, TOKEN)
        first = self.result.trains[0]
        second = replace(first, number='328')
        result = Observation(watch, (first,second,first),1000)
        self.assertEqual(len(self.store.observe('both',1,result,1000)),1)
        sent=[]
        def transport(endpoint,payload):
            sent.append(payload)
            return {'data':{'status':'ok','id':'group'}}
        self.store.deliver_one(transport,1001)
        self.assertIsNone(self.store.deliver_one(transport,1002))
        self.assertEqual(sent[0]['data']['trainCount'],2)
        self.assertIn('총 2편 예매 가능',sent[0]['body'])
        self.assertEqual(self.store.observe('both',1,result,1003),[])
        third=replace(first,number='330')
        updated=replace(result,trains=(first,second,third),observed_at=1300)
        self.assertEqual(len(self.store.observe('both',1,updated,1300)),1)
        self.store.deliver_one(transport,1301)
        self.assertEqual(sent[-1]['data']['trainCount'],3)

    def test_existing_individual_alerts_do_not_repeat_after_upgrade(self):
        from server.monitor import encode_trains
        with self.store.connect() as db:
            db.execute("""INSERT INTO alerts(id,watch_id,revision,fingerprint,trains,observed_at,created_at,state)
                          VALUES('legacy','w1',1,'old',?,1000,1000,'device_received')""",
                       (encode_trains(self.result.trains),))
        self.assertEqual(self.store.observe('w1',1,self.result,1001),[])

if __name__ == "__main__":
    unittest.main()
