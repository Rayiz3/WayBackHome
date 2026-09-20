"""Personal API. Bind locally; use a TLS reverse proxy for phone access."""
from datetime import date, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hmac
import json
import os
import re
from urllib.parse import urlsplit

from server.monitor import Store
from server.seat_alerts import Watch


def decode_settings(data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    def integer(v):
        if type(v) is not int:
            raise ValueError("date/time fields must be integers")
        return v
    day = data["date"]
    start, end = data["from"], data["to"]
    if not isinstance(data["departure"], str) or not isinstance(data["arrival"], str):
        raise ValueError("Invalid stations")
    departure, arrival = data["departure"].strip(), data["arrival"].strip()
    if not departure or not arrival or max(len(departure),len(arrival)) > 80:
        raise ValueError("Invalid stations")
    if data.get("adults") != "1":
        raise ValueError("현재 실조회 검증은 성인 1명만 지원합니다.")
    if type(data["standard"]) is not bool or type(data["first"]) is not bool:
        raise ValueError("Invalid seat classes")
    numbers = data.get("trainNumbers", "")
    if not isinstance(numbers,str) or (numbers.strip() and not re.fullmatch(r"\d{1,5}(\s*,\s*\d{1,5})*",numbers.strip())):
        raise ValueError("Invalid train numbers")
    return Watch(date(integer(day["year"]),integer(day["month"]),integer(day["day"])),departure,arrival,
        time(integer(start["hour"]),integer(start["minute"])),time(integer(end["hour"]),integer(end["minute"])),
        tuple(k for k, enabled in [("standard",data["standard"]),("first",data["first"])] if enabled),
        tuple(dict.fromkeys(str(int(n.strip())) for n in numbers.split(",") if n.strip())))


class API:
    def __init__(self, store, secret):
        if len(secret) < 32:
            raise ValueError("WAYBACKHOME_API_KEY must contain at least 32 characters")
        self.store, self.secret = store, secret

    def dispatch(self, method, path, authorization, body=None):
        if method == "GET" and path == "/health":
            return 200, {"status":"ok"}
        expected = "Bearer " + self.secret
        if not hmac.compare_digest(authorization.encode(),expected.encode()):
            return 401, {"error":"서버 연결 키가 올바르지 않습니다."}
        if method == "GET" and path == "/connection":
            return 200, {"status":"connected","worker_live":self.store.worker_live()}
        match = re.fullmatch(r"/watches/([A-Za-z0-9_-]{1,128})",path)
        try:
            if match:
                watch_id = match[1]
                if method == "PUT":
                    if not isinstance(body,dict):
                        raise ValueError("Invalid request body")
                    self.store.put(watch_id,decode_settings(body["settings"]),body["token"])
                    return 200,self.status(watch_id)
                if method == "GET":
                    return (200,self.status(watch_id)) if self.store.get(watch_id) else (404,{"error":"감시를 찾을 수 없습니다."})
                if method == "DELETE":
                    self.store.stop(watch_id)
                    return 200,{"status":"stopped"}
            ack = re.fullmatch(r"/alerts/([A-Za-z0-9-]{1,128})/received",path)
            if ack and method == "POST":
                self.store.acknowledge(ack[1])
                return 200,{"status":"device_received"}
        except (ValueError,KeyError,TypeError,OverflowError) as error:
            return 400,{"error":str(error) if isinstance(error,ValueError) else "요청 데이터 형식이 올바르지 않습니다."}
        return 404,{"error":"경로를 찾을 수 없습니다."}

    def status(self, watch_id):
        row = self.store.get(watch_id)
        return {key:row[key] for key in ("id","enabled","revision","status","checked_at","error","next_check")} | {
            "alerts":self.store.alerts(watch_id)[:20], "worker_live":self.store.worker_live()
        }


def handler_for(api):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            pass  # Never log credentials, device tokens, or query payloads.

        def do_GET(self):
            self.handle_request()

        def do_PUT(self):
            self.handle_request()

        def do_DELETE(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            try:
                length = int(self.headers.get("Content-Length","0"))
                if not 0 <= length <= 65536:
                    self.reply(413,{"error":"요청이 너무 큽니다."})
                    return
                body = json.loads(self.rfile.read(length)) if length else None
                code, result = api.dispatch(self.command,urlsplit(self.path).path,
                                            self.headers.get("Authorization",""),body)
                self.reply(code,result)
            except (ValueError,UnicodeDecodeError):
                self.reply(400,{"error":"JSON 요청을 확인해 주세요."})
            except Exception:
                self.reply(500,{"error":"서버 처리 오류가 발생했습니다."})

        def reply(self,code,data):
            raw = json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(raw)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8787)
    parser.add_argument("--db",default="server/monitor.db")
    args = parser.parse_args()
    api = API(Store(args.db),os.environ.get("WAYBACKHOME_API_KEY",""))
    print(f"WayBackHome API: {args.host}:{args.port}. A separate live query worker is required.")
    server = ThreadingHTTPServer((args.host,args.port),handler_for(api))
    server.timeout = 30
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
