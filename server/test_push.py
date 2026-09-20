"""Explicit manual push test; never creates a seat observation or seat alert."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from functools import partial
from datetime import datetime, timezone
from server.seat_alerts import post_expo, check_receipt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--watch', help='Use this existing watch device, even when monitoring is stopped')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent / '.local'
    record = directory / 'test-push.json'
    transport = partial(post_expo, access_token=os.environ.get('EXPO_ACCESS_TOKEN'))
    if args.send:
        with sqlite3.connect(directory / 'monitor.db') as db:
            rows = db.execute('SELECT DISTINCT token FROM watches WHERE id=?', (args.watch,)) if args.watch else db.execute('SELECT DISTINCT token FROM watches WHERE enabled=1')
            tokens = [r[0] for r in rows]
        if len(tokens) != 1:
            raise ValueError('Expected exactly one registered device; select a device before sending')
        result = transport('send', {
            'to': tokens[0], 'title': 'WayBackHome 테스트 푸시',
            'body': '원격 푸시 수신 확인용입니다. 실제 열차 좌석 발견 알림이 아닙니다.',
            'sound': 'default', 'channelId': 'seat-alerts', 'priority': 'high', 'ttl': 300,
            'data': {'kind': 'manual_test'},
        })
        ticket = result.get('data', {})
        saved = {'sent_at': datetime.now(timezone.utc).isoformat(), 'ticket': ticket}
        record.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(saved, ensure_ascii=True))
    else:
        saved = json.loads(record.read_text(encoding='utf-8'))
        ticket = saved['ticket']
        if ticket.get('status') != 'ok':
            print(json.dumps(ticket, ensure_ascii=True))
            return
        status = check_receipt(ticket['id'], transport)
        saved['receipt'] = status
        record.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'receipt': status}))

if __name__ == '__main__':
    main()
