"""One live read-only query through the same provider as the worker; never sends."""
import argparse
from datetime import date, time
import json
from playwright.sync_api import sync_playwright
from server.korail import KorailProvider
from server.seat_alerts import Watch, matching_trains

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--date",required=True,type=date.fromisoformat)
    parser.add_argument("--departure",required=True)
    parser.add_argument("--arrival",required=True)
    parser.add_argument("--from-time",default="12:00",type=time.fromisoformat)
    parser.add_argument("--to-time",default="23:59",type=time.fromisoformat)
    parser.add_argument("--diagnostics",action="store_true")
    parser.add_argument("--browser", choices=['chromium', 'msedge', 'chrome'], default='chromium')
    parser.add_argument("--inspect", action='store_true', help='Show browser and stop on failure for manual inspection')
    parser.add_argument("--stop-before-date", action='store_true', help='Leave the browser open after selecting stations, without selecting date or querying')
    args=parser.parse_args()
    watch=Watch(args.date,args.departure,args.arrival,args.from_time,args.to_time)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=not (args.inspect or args.stop_before_date), **({'channel': args.browser} if args.browser != 'chromium' else {}))
        provider=KorailProvider(browser, 'server/.local/diagnostics' if args.diagnostics else None, inspect=args.inspect, stop_before_date=args.stop_before_date)
        try:
            result=provider.query(watch)
            matching=matching_trains(watch,watch.day,result.trains)
            print(json.dumps({"status":result.status,"total":len(result.trains),"matching":len(matching),
                "trains":[{"number":t.number,"departure":t.start.isoformat(),"standard":t.standard,"first":t.first}
                          for t in matching]},ensure_ascii=False))
        finally:
            provider.close()
            browser.close()

if __name__ == "__main__":
    main()
