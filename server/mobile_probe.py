"""Bounded, unauthenticated availability probe; never books or logs in."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--date', default='2026-09-30')
    parser.add_argument('--time', default='12:00')
    parser.add_argument('--departure', default='부산')
    parser.add_argument('--arrival', default='수서')
    parser.add_argument('--max-pages', type=int, choices=range(1, 7), default=1)
    args = parser.parse_args()
    moment = datetime.fromisoformat(args.date + 'T' + args.time)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / '.tools' / 'korail-probe-libs'))
    from pykorail import Korail
    from pykorail.constants import API_ENDPOINTS
    from pykorail.options import TrainType

    report = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'query': vars(args), 'requests': [], 'trains': []}
    fields = ('h_trn_no', 'h_trn_clsf_nm', 'h_trn_clsf_cd', 'h_trn_gp_cd',
              'h_dpt_dt', 'h_dpt_tm', 'h_arv_dt', 'h_arv_tm',
              'h_dpt_rs_stn_nm', 'h_arv_rs_stn_nm', 'h_gen_rsv_cd',
              'h_spe_rsv_cd', 'h_wait_rsv_flg', 'h_rsv_psb_flg', 'h_rsv_psb_nm')
    with Korail(validate_stations=False) as client:
        session = client._api._session
        original_post = session.post
        cursor = {}
        more = False

        def bounded_post(url, **kwargs):
            nonlocal more, cursor
            if url != API_ENDPOINTS['search_schedule'] or len(report['requests']) >= args.max_pages:
                raise RuntimeError('Schedule request limit exceeded')
            kwargs['params'].update(cursor)
            item = {'method': 'POST', 'endpoint': url}
            report['requests'].append(item)
            response = original_post(url, timeout=25, allow_redirects=False, **kwargs)
            item['http_status'] = response.status_code
            payload = response.json()
            item.update({key: payload.get(key) for key in ('strResult', 'h_msg_cd', 'h_msg_txt')})
            item['schema'] = sorted(payload)
            item['pagination'] = {key: payload.get(key) for key in
                                  ('h_next_pg_flg', 'h_qry_st_no_next', 'h_trn_no_next', 'h_rslt_cnt')}
            more = payload.get('h_next_pg_flg') == 'Y'
            rows = payload.get('trn_infos', {}).get('trn_info', [])
            if more:
                # This server returns Y but null opaque cursors. Overlap the last
                # departure time instead of adding a minute and skipping ties.
                last_time = rows[-1]['h_dpt_tm'] if isinstance(rows, list) and rows else None
                next_cursor = {'txtGoHour': last_time}
                if not isinstance(last_time, str) or len(last_time) != 6 or next_cursor == cursor:
                    raise ValueError('Missing or stalled time continuation')
                cursor = next_cursor
            if isinstance(rows, list):
                existing = {(row['h_trn_no'], row['h_dpt_dt'], row['h_dpt_tm']) for row in report['trains']}
                for row in rows:
                    identity = (row.get('h_trn_no'), row.get('h_dpt_dt'), row.get('h_dpt_tm'))
                    if identity not in existing:
                        report['trains'].append({key: row.get(key) for key in fields})
                        existing.add(identity)
            return response

        session.post = bounded_post
        try:
            for page in range(args.max_pages):
                if page:
                    time.sleep(5)
                client.trains.search(args.departure, args.arrival, depart_after=moment,
                                     train_type=TrainType.KTX, include_no_seats=True)
                if not more:
                    break
            report['outcome'] = 'partial' if more else 'response_received'
            report['pagination_complete'] = not more
        except Exception as exc:
            # Exception text can contain signed request URLs; save only its type.
            report['outcome'] = 'failed'
            report['exception_type'] = type(exc).__name__
    directory = root / 'server' / '.local' / 'diagnostics'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('mobile-probe-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Report:', path)


if __name__ == '__main__':
    main()
