import unittest
from datetime import date, time
from server.seat_alerts import Watch, parse_cards, matching_trains, send_alert, check_receipt, PushError

# Actual visible card observed on Korail 2026-09-17 for 2026-10-07.
CARD = """<li class="tckList clear"><div class="tck_inner"><div class="info_inner fl-l"><div class="info_box"><div class="tit_box type02"><div class="flag_wrap type2"><span class="train_sancheon_ticket"><span class="blind">KTX-산천</span></span><span class="num">326</span></div></div><div class="data_box right"><h3 class="txt_bk"><span>부산</span> → <span>수서</span><span>(12:12 ~ 14:52)</span></h3><p class="s_txt">소요시간: 2시간 40분</p></div></div></div><div class="price_box fl-l gen"><div class="inner type02"><a href="#none"><p class="txt_ch">일반실</p><p class="txt_price txt_bk">52,300원</p><p class="txt_gr">5%적립</p></a></div></div><div class="price_box fl-l spe sold_out_soon"><div class="inner type02"><a href="#none"><p class="txt_ch">특실(매진임박)</p><p class="txt_price txt_bk">76,100원</p><p class="txt_gr">5%적립</p></a></div></div></div></li>"""
WATCH = Watch(date(2026,10,7), "부산", "수서", time(12), time(23,59))

class SeatTests(unittest.TestCase):
    def test_real_card(self):
        train = parse_cards(CARD)[0]
        self.assertEqual((train.number, train.standard, train.first), ("326","available","available"))
        self.assertEqual(len(matching_trains(WATCH, WATCH.day, [train])), 1)

    def test_date_route_time_and_number(self):
        train = parse_cards(CARD)[0]
        with self.assertRaises(ValueError):
            matching_trains(WATCH, date(2026,10,8), [train])
        for watch in [
            Watch(WATCH.day,"부산","서울",time(12),time(20)),
            Watch(WATCH.day,"부산","수서",time(13),time(20)),
            Watch(WATCH.day,"부산","수서",time(12),time(20),train_numbers=("330",)),
        ]:
            self.assertEqual(matching_trains(watch, watch.day, [train]), [])

    def test_sold_out_and_unknown_never_notify(self):
        html = CARD.replace("일반실", "매진").replace("특실(매진임박)", "매진")
        self.assertEqual(matching_trains(WATCH,WATCH.day,parse_cards(html)), [])
        html = CARD.replace("52,300원","조회중").replace("76,100원","조회중")
        self.assertEqual(matching_trains(WATCH,WATCH.day,parse_cards(html)), [])
        with self.assertRaises(ValueError):
            send_alert("ExpoPushToken[test]",WATCH,parse_cards(html),"event-1")

    def test_structure_change_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_cards(CARD.replace("12:12 ~ 14:52","unknown"))
        with self.assertRaises(ValueError):
            parse_cards(CARD.replace("</li>",""))

    def test_ticket_and_receipt_are_not_device_receipt(self):
        sent = []
        def transport(endpoint,payload):
            sent.append((endpoint,payload))
            return {"data":{"status":"ok","id":"ticket-1"}}
        ticket = send_alert("ExpoPushToken[test]",WATCH,parse_cards(CARD),"event-1",transport)
        self.assertEqual(ticket,"ticket-1")
        self.assertEqual(sent[0][1]["channelId"],"seat-alerts")
        self.assertIn("12:12",sent[0][1]["body"])
        self.assertEqual(check_receipt(ticket,lambda *_: {"data":{}}),"pending")
        self.assertEqual(check_receipt(ticket,lambda *_: {"data":{ticket:{"status":"ok"}}}),"provider_accepted")
        with self.assertRaises(PushError) as error:
            check_receipt(ticket,lambda *_: {"data":{ticket:{"status":"error","details":{"error":"DeviceNotRegistered"}}}})
        self.assertEqual(error.exception.code,"DeviceNotRegistered")

if __name__ == "__main__":
    unittest.main()

