"""Read-only Korail website adapter, using the observed booking UI.

No private API, booking, queue bypass, or CAPTCHA handling. Stop on unknown UI.
Live end-to-end validation is required after website changes.
"""
from datetime import date
import re
import time
from playwright.sync_api import expect, TimeoutError as PlaywrightTimeout
from server.monitor import Observation
from server.seat_alerts import parse_cards

URL = "https://www.korail.com/ticket/search/general"


class KorailProvider:
    def __init__(self, browser, diagnostic_directory=None, inspect=False, stop_before_date=False):
        self.stop_before_date = stop_before_date
        self.inspect = inspect
        self.diagnostic_directory = diagnostic_directory
        self.context = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
        self.context.set_default_timeout(15000)

    def close(self):
        self.context.close()

    def query(self, watch):
        page = self.context.new_page()
        self.query_http_error = None
        held = False
        def hold(reason):
            nonlocal held
            if self.inspect and not held:
                held = True
                print(f"INSPECTION PAUSED: {reason}. Browser stays open; no further automation.", flush=True)
                input("Press Enter only when finished inspecting to close the browser: ")
        def remember_server_failure(response):
            from urllib.parse import urlsplit
            if (response.status >= 500 and response.request.resource_type in ('xhr', 'fetch')
                    and urlsplit(response.url).hostname == 'www.korail.com'):
                self.query_http_error = response.status
                hold(f"HTTP {response.status} from {response.request.method} {response.url.split('?')[0]}")
        page.on('response', remember_server_failure)
        failures = []
        if self.diagnostic_directory:
            from urllib.parse import urlsplit
            def failed(request):
                url = urlsplit(request.url)
                failures.append({'host': url.hostname, 'path': url.path, 'failure': request.failure})
            def response_error(response):
                if response.status >= 400 or response.request.resource_type in ('xhr', 'fetch'):
                    url = urlsplit(response.url)
                    failures.append({'host': url.hostname, 'path': url.path, 'status': response.status})
            page.on('requestfailed', failed)
            page.on('response', response_error)
            page.on('pageerror', lambda error: failures.append({'page_error': str(error)[:500]}))
        # Public service notices can arrive after the form has already loaded.
        # Close the notice through its visible control before resuming actions.
        try:
            result = self._query(page, watch)
            hold("Query completed without an HTTP 500")
            return result
        except Exception as error:
            hold(f"{type(error).__name__}: {str(error)[:250]}")
            if self.diagnostic_directory:
                from pathlib import Path
                directory = Path(self.diagnostic_directory)
                directory.mkdir(parents=True, exist_ok=True)
                import json
                (directory / 'query-failures.json').write_text(json.dumps(failures, ensure_ascii=False), encoding='utf-8')
                page.screenshot(path=str(directory / 'query-error.png'), full_page=True)
                (directory / 'query-error.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
            raise
        finally:
            page.close()

    def _station(self, page, label, name):
        page.get_by_role("link", name=label + " 선택", exact=True).click()
        page.get_by_role("textbox", name="역명을 입력해주세요", exact=True).fill(name)
        page.get_by_role("button", name="검색", exact=True).click()
        # The same name can also appear in recent stations; use the search result.
        page.get_by_role("link", name=name, exact=True).last.click()
        if page.get_by_role("textbox", name=label, exact=True).input_value() != name:
            raise ValueError("Station selection did not apply")

    def _date_time(self, page, watch, retry=True):
        page.get_by_role("link", name="출발일", exact=True).click()
        calendar = page.get_by_role("table", name="달력", exact=True)
        for _ in range(13):
            page.wait_for_function("""() => [...document.querySelectorAll('.type_date-pop .slick-track')]
                .every(track => !track.style.transition)""")
            label = calendar.locator("../..").locator("p.date").inner_text()
            match = re.search(r"(\d{4})\.\s*(\d{2})\.",label)
            if not match:
                raise ValueError("Calendar month label changed")
            current = (int(match[1]),int(match[2]))
            target = (watch.day.year,watch.day.month)
            if current == target:
                break
            page.get_by_role("button",name="Next" if current < target else "Previous",exact=True).first.click()
            # The carousel updates its accessible month after the slide animation.
            # Do not click Next again while the previous month is still active.
            expect(calendar.locator("../..").locator("p.date")).not_to_have_text(label)
        else:
            raise ValueError("Date is outside supported calendar")
        target_calendar = page.locator(".datepicker").filter(
            has=page.locator("p.date").filter(has_text=re.compile(
                rf"^{watch.day.year}\.\s*{watch.day.month:02d}\.$")))
        try:
            target_calendar.get_by_role("link",name=re.compile(r"^" + str(watch.day.day) + r"(?:\s|$)")).click()
        except PlaywrightTimeout as exc:
            if retry:
                page.get_by_role("button", name="레이어닫기", exact=True).click()
                return self._date_time(page, watch, retry=False)
            raise ValueError("Requested date did not become selectable; query unverified") from exc
        target_hour = f"{watch.start.hour:02d}시"
        for _ in range(12):
            page.wait_for_function("""() => [...document.querySelectorAll('.timeSelect .slick-track')]
                .every(track => !track.style.transition)""")
            link = page.get_by_role("link",name=target_hour,exact=True)
            if link.is_visible():
                try:
                    link.click(timeout=1500)
                except PlaywrightTimeout:
                    # Selecting a different day asynchronously resets the hour
                    # carousel to midnight. Re-read it instead of clicking stale UI.
                    continue
                break
            shown = page.get_by_role("link",name=re.compile(r"^\d{2}시$")).all_text_contents()
            hours = [int(v[:2]) for v in shown if re.fullmatch(r"\d{2}시",v.strip())]
            if not hours:
                raise ValueError("Hour selector changed")
            try:
                page.get_by_role("button",name="Next" if watch.start.hour > max(hours) else "Previous",exact=True).last.click(timeout=1500)
                expect(page.get_by_role("link",name=re.compile(r"^\d{2}시$"))).not_to_have_text(shown, timeout=1500)
            except (PlaywrightTimeout, AssertionError):
                continue
        else:
            raise ValueError("Could not select hour")
        page.get_by_role("button",name="적용",exact=True).click()
        self._verify_date(page, watch)

    def _verify_date(self,page,watch):
        value = page.locator("#startDate").input_value()
        if not value.startswith(watch.day.isoformat()) or not value.endswith(f"{watch.start.hour:02d}:00"):
            raise ValueError("Query date/hour does not match requested condition")

    def _passengers(self,page):
        page.get_by_role("link",name="총 1명",exact=True).click()
        adult = page.get_by_role("button",name="어른 인원 감소 버튼",exact=True).locator("..").inner_text().strip()
        if adult != "1":
            raise ValueError("Query does not contain exactly one adult")
        for name in ["어린이","유아","경로","중증","경증","국가유공자"]:
            count = page.get_by_role("button",name=name+" 인원 감소 버튼",exact=True).locator("..").inner_text().strip()
            if count != "0":
                raise ValueError("Unexpected additional passenger")
        page.get_by_role("button",name="적용",exact=True).click()
        expect(page.get_by_text("어른 : 1명",exact=True)).to_be_visible()
        expect(page.get_by_text("선택하신 인원이 확실한가요?",exact=False)).to_be_visible()
        page.get_by_role("button",name="예",exact=True).click()

    def _wait_results(self,page):
        # Queue exit alone is not completion. Wait for a terminal visible result.
        condition = """() => {
            const visible = e => e && e.getClientRects().length > 0;
            const queue = document.querySelector('#nf-vwr-cancel');
            if (visible(queue)) return false;
            // The site briefly renders its empty-state message before loading
            // real results. That message alone cannot prove there are no trains.
            return [...document.querySelectorAll('li.tckList')].some(visible);
        }"""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.query_http_error:
                raise ValueError(f"Korail request failed with HTTP {self.query_http_error}; result unverified")
            try:
                page.wait_for_function(condition, timeout=1000)
                if self.query_http_error:
                    raise ValueError(f"Korail request failed with HTTP {self.query_http_error}; result unverified")
                return
            except PlaywrightTimeout:
                pass
        raise PlaywrightTimeout("Korail results did not complete within 120 seconds")

    def _query(self,page,watch):
        page.goto("https://www.korail.com/ticket/main",wait_until="domcontentloaded")
        # Let the optional announcement finish opening before opening our own
        # modal; overlapping modals corrupt the calendar's enabled state.
        try:
            close = page.get_by_text("창닫기", exact=True)
            close.wait_for(state="visible", timeout=5000)
            close.click()
        except PlaywrightTimeout:
            pass
        page.add_locator_handler(page.get_by_text("창닫기", exact=True), lambda close: close.click())
        page.get_by_role("link",name="승차권 예매",exact=True).click()
        page.wait_for_url(URL)
        self._station(page,"출발역",watch.departure)
        self._station(page,"도착역",watch.arrival)
        if self.stop_before_date:
            print("INSPECTION PAUSED: Stations selected. Date/time dialog has NOT been opened. No further automation.", flush=True)
            input("Press Enter only when finished inspecting to close the browser: ")
            raise SystemExit(0)
        self._date_time(page,watch)
        self._passengers(page)
        page.get_by_role("button",name="열차 조회",exact=True).click()
        page.wait_for_url("**/ticket/search/list")
        category = page.get_by_role("button",name="KTX/KTX-산천",exact=True)
        if category.get_attribute("aria-pressed") != "true":
            category.click()
        self._wait_results(page)
        self._verify_date(page,watch)
        if page.locator("#labelstart").input_value() != watch.departure or page.locator("#labelend").input_value() != watch.arrival:
            raise ValueError("Result route does not match requested route")
        if page.locator("#labelple").input_value() != "총 1명":
            raise ValueError("Result passenger count changed")
        if not page.get_by_role("link",name="직통",exact=True).is_visible():
            raise ValueError("Only direct services are supported")
        for label in ["왕복","인접역 보기","서울·용산 - 수서 함께 보기"]:
            if page.get_by_role("checkbox",name=label,exact=True).is_checked():
                raise ValueError("Unexpected journey expansion")
        observed_at = time.time()
        # All train categories may be returned; the domain filter includes every KTX variant.
        for _ in range(30):
            more = page.get_by_role("link",name="더보기",exact=True)
            if not more.is_visible():
                break
            before = page.locator("li.tckList").count()
            more.click()
            page.wait_for_function("""count => document.querySelectorAll('li.tckList').length > count ||
                ![...document.querySelectorAll('a')].some(a => a.textContent.trim() === '더보기' && a.getClientRects().length)""",
                arg=before,timeout=120000)
            self._wait_results(page)
            if time.time() - observed_at > 120:
                raise ValueError("Pagination made the first result stale")
        else:
            raise ValueError("Pagination did not terminate")
        self._verify_date(page,watch)
        html = page.locator("li.tckList").evaluate_all("cards => cards.map(c => c.outerHTML).join('')")
        trains = tuple(parse_cards(html))
        if len({(t.number,t.start) for t in trains}) != len(trains):
            raise ValueError("Duplicate result cards")
        return Observation(watch,trains,observed_at)
