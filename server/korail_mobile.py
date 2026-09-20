"""Read-only mobile API provider. No login, booking, or browser runtime."""
from datetime import datetime
import time

from server.monitor import Observation
from server.seat_alerts import Train


def parse_row(row, watch):
    def required(key):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing train field: ' + key)
        return value.strip()

    if required('h_dpt_dt') != watch.day.strftime('%Y%m%d'):
        raise ValueError('Unexpected departure date')
    departure, arrival = required('h_dpt_rs_stn_nm'), required('h_arv_rs_stn_nm')
    if (departure, arrival) != (watch.departure, watch.arrival):
        raise ValueError('Unexpected route')
    family = required('h_trn_clsf_nm')
    if not family.startswith('KTX'):
        raise ValueError('Unexpected train family')
    number = required('h_trn_no')
    if not number.isdigit():
        raise ValueError('Invalid train number')
    def seat(key):
        return {'11': 'available', '13': 'sold_out', '00': 'unavailable'}.get(required(key), 'unknown')
    return Train(str(int(number)), family, departure, arrival,
                 datetime.strptime(required('h_dpt_tm'), '%H%M%S').time(),
                 datetime.strptime(required('h_arv_tm'), '%H%M%S').time(),
                 seat('h_gen_rsv_cd'), seat('h_spe_rsv_cd'))


class KorailMobileProvider:
    def __init__(self, client=None, clock=time.time, sleep=time.sleep, max_pages=8):
        if client is None:
            from pykorail import Korail
            client = Korail(validate_stations=False)
        self.client, self.clock, self.sleep = client, clock, sleep
        self.max_pages = max_pages
        self.last_request = None

    def close(self):
        self.client.close()

    def query(self, watch):
        from pykorail.constants import API_ENDPOINTS, APP_VERSION, DEVICE
        from pykorail.options import TrainType
        url = API_ENDPOINTS['search_schedule']
        started = self.clock()
        cursor = watch.start.strftime('%H%M%S')
        trains = {}
        for _ in range(self.max_pages):
            if self.last_request is not None:
                self.sleep(max(0, 5 - (self.clock() - self.last_request)))
            if self.clock() - started > 90:
                raise TimeoutError('Incomplete query exceeded freshness window')
            headers, _ = self.client._api.sign(url)
            params = dict(Device=DEVICE, Version=APP_VERSION, Sid='', txtMenuId='11',
                          radJobId='1', selGoTrain=TrainType.KTX, txtTrnGpCd=TrainType.KTX,
                          txtGoStart=watch.departure, txtGoEnd=watch.arrival,
                          txtGoAbrdDt=watch.day.strftime('%Y%m%d'), txtGoHour=cursor,
                          txtPsgFlg_1=watch.adults, txtPsgFlg_2=0, txtPsgFlg_3=0,
                          txtPsgFlg_4=0, txtPsgFlg_5=0, txtSeatAttCd_2='000',
                          txtSeatAttCd_3='000', txtSeatAttCd_4='015',
                          ebizCrossCheck='N', srtCheckYn='N', rtYn='N', adjStnScdlOfrFlg='N')
            self.last_request = self.clock()
            response = self.client._api._session.post(url, params=params, headers=headers,
                                                      timeout=25, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError('Korail HTTP failure')
            payload = response.json()
            if not isinstance(payload, dict) or payload.get('strResult') != 'SUCC':
                raise ValueError('Korail application failure')
            rows = payload.get('trn_infos', {}).get('trn_info')
            more = payload.get('h_next_pg_flg')
            if not isinstance(rows, list) or more not in ('Y', 'N'):
                raise ValueError('Unknown result schema')
            page = [parse_row(row, watch) for row in rows]
            if any(t.start.strftime('%H%M%S') < cursor for t in page):
                raise ValueError('Server ignored time cursor')
            if page != sorted(page, key=lambda t: t.start):
                raise ValueError('Unordered results')
            for train in page:
                if train.start <= watch.end:
                    trains[(train.number, train.start)] = train
            if more == 'N' or (page and page[-1].start > watch.end):
                return Observation(watch, tuple(trains.values()), started)
            if not page or page[-1].start.strftime('%H%M%S') <= cursor:
                raise ValueError('Stalled pagination')
            cursor = page[-1].start.strftime('%H%M%S')
        raise ValueError('Page limit reached; refusing partial result')
