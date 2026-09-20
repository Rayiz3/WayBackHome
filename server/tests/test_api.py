import tempfile
import unittest
from pathlib import Path
from server.api import API
from server.monitor import Store

SETTINGS = {"date":{"year":2026,"month":10,"day":7},"departure":"부산","arrival":"수서",
            "from":{"hour":12,"minute":0},"to":{"hour":23,"minute":59},
            "adults":"1","trainNumbers":"","standard":True,"first":True}

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/"db")
        self.api = API(self.store,"x"*32)
        self.auth = "Bearer " + "x"*32
        self.body = {"settings":SETTINGS,"token":"ExpoPushToken[test]"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_authentication_required_for_writes_and_read(self):
        for method in ["GET","PUT","DELETE"]:
            self.assertEqual(self.api.dispatch(method,"/watches/a","",self.body)[0],401)
        self.assertEqual(self.api.dispatch("POST","/alerts/a/received","")[0],401)
        self.assertIsNone(self.store.get("a"))

    def test_register_read_stop_and_no_token_in_response(self):
        code,data = self.api.dispatch("PUT","/watches/a",self.auth,self.body)
        self.assertEqual(code,200)
        self.assertEqual(data["status"],"pending")
        self.assertNotIn("token",data)
        self.assertEqual(self.api.dispatch("GET","/watches/a",self.auth)[0],200)
        self.api.dispatch("DELETE","/watches/a",self.auth)
        self.assertFalse(self.store.get("a")["enabled"])

    def test_invalid_calendar_and_unsupported_passengers(self):
        for overrides in [{"date":{"year":2026,"month":2,"day":29}},{"adults":"2"},
                          {"standard":"true"},{"trainNumbers":"18,,32"},
                          {"from":{"hour":True,"minute":0}},{"departure":""}]:
            body = {**self.body,"settings":{**SETTINGS,**overrides}}
            self.assertEqual(self.api.dispatch("PUT","/watches/a",self.auth,body)[0],400)
        self.assertIsNone(self.store.get("a"))

    def test_unknown_ack_does_not_create_success(self):
        self.assertEqual(self.api.dispatch("POST","/alerts/absent/received",self.auth)[0],400)

if __name__ == "__main__":
    unittest.main()

