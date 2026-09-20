"""Run the personal PC API and live Korail worker together."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import signal
import threading

from server.api import API, handler_for
from server.korail_mobile import KorailMobileProvider
from server.monitor import Store
from server.seat_alerts import post_expo
from server.worker import Worker


def connection_key(directory):
    configured = os.environ.get("WAYBACKHOME_API_KEY")
    if configured:
        if len(configured) < 32:
            raise ValueError("WAYBACKHOME_API_KEY must contain at least 32 characters")
        return configured
    directory.mkdir(parents=True,exist_ok=True)
    path = directory / "server-key.txt"
    try:
        with path.open("x",encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError("Saved server key is invalid")
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=int(os.environ.get("PORT", "8787")))
    parser.add_argument("--host",default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--show-key",action="store_true",help="Display the local pairing key in your own terminal")
    args = parser.parse_args()
    directory = Path(os.environ.get("WAYBACKHOME_DATA_DIR", str(Path(__file__).resolve().parent / ".local")))
    directory.mkdir(parents=True, exist_ok=True)
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("WAYBACKHOME_API_KEY"):
        raise ValueError("Public binding requires WAYBACKHOME_API_KEY")
    key = connection_key(directory)
    if args.show_key:
        print(key)
        return
    store = Store(directory / "monitor.db")
    api = API(store,key)
    httpd = ThreadingHTTPServer((args.host,args.port),handler_for(api))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    thread = threading.Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    print(f"API ready on {args.host}:{args.port}",flush=True)
    try:
        provider = KorailMobileProvider()
        transport = partial(post_expo,access_token=os.environ.get("EXPO_ACCESS_TOKEN"))
        try:
            print("Mobile API query worker starting (no browser/login). Keep this PC awake.",flush=True)
            Worker(store,provider,transport).run(stop)
        finally:
            provider.close()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
