import unittest
from datetime import date, time
from types import SimpleNamespace
from server.korail_mobile import KorailMobileProvider
from server.seat_alerts import Watch

WATCH = Watch(date(2026, 9, 30), '부산', '수서', time(12), time(20))

def row(number, departure, standard='11'):
    return dict(h_trn_no=number, h_trn_clsf_nm='KTX-산천', h_dpt_dt='20260930',
                h_dpt_rs_stn_nm='부산', h_arv_rs_stn_nm='수서', h_dpt_tm=departure,
                h_arv_tm='230000', h_gen_rsv_cd=standard, h_spe_rsv_cd='13')

def page(rows, more='N'):
    return dict(strResult='SUCC', h_next_pg_flg=more, trn_infos={'trn_info': rows})


class ProviderTests(unittest.TestCase):
    def provider(self, responses, max_pages=8):
        self.calls = []
        def post(url, **kwargs):
            self.calls.append(kwargs)
            payload = responses.pop(0)
            return SimpleNamespace(status_code=200, json=lambda: payload)
        client = SimpleNamespace(_api=SimpleNamespace(sign=lambda _: ({}, None),
                                 _session=SimpleNamespace(post=post)))
        return KorailMobileProvider(client, clock=lambda:100, sleep=lambda _:None, max_pages=max_pages)

    def test_overlap_preserves_sold_out_and_unknown(self):
        provider = self.provider([page([row('326','121200'),row('328','123900')],'Y'),
                                  page([row('328','123900'),row('346','160400','13'),row('348','164300','XX')])])
        result = provider.query(WATCH)
        self.assertEqual(len(result.trains),4)
        self.assertEqual(result.trains[2].standard,'sold_out')
        self.assertEqual(result.trains[3].standard,'unknown')
        self.assertEqual(self.calls[1]['params']['txtGoHour'],'123900')
        self.assertEqual(self.calls[0]['timeout'],25)
        self.assertEqual(self.calls[0]['params']['selGoTrain'],'100')

    def test_partial_error_never_returns_observation(self):
        provider = self.provider([page([row('326','121200')],'Y'), {'strResult':'FAIL','h_msg_cd':'MACRO ERROR'}])
        with self.assertRaises(ValueError): provider.query(WATCH)

    def test_stall_and_cap_reject_partial_results(self):
        for responses, cap in [([page([row('326','120000')],'Y')],8),
                               ([page([row('326','121200')],'Y')],1)]:
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.provider(responses,cap).query(WATCH)

    def test_wrong_route_or_missing_status_fails(self):
        wrong = row('326','121200')
        wrong['h_arv_rs_stn_nm']='서울'
        for payload in [page([wrong]), {'strResult':'SUCC','trn_infos':{'trn_info':[]}}]:
            with self.assertRaises(ValueError): self.provider([payload]).query(WATCH)

    def test_stop_after_window_and_new_watch_values(self):
        result = self.provider([page([row('326','121200'),row('368','230000')],'Y')]).query(WATCH)
        self.assertEqual(len(result.trains),1)
        self.assertEqual(self.calls[0]['params']['txtGoAbrdDt'],'20260930')
