"""Verified Korail card parsing and Expo transport; no booking actions."""
from dataclasses import dataclass
from datetime import date, time
from html.parser import HTMLParser
import json
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

@dataclass(frozen=True)
class Watch:
    day: date
    departure: str
    arrival: str
    start: time
    end: time
    classes: tuple[str, ...] = ("standard", "first")
    train_numbers: tuple[str, ...] = ()
    adults: int = 1

    def __post_init__(self):
        if self.start > self.end or self.departure == self.arrival:
            raise ValueError("Invalid route or time window")
        if self.adults != 1:
            raise ValueError("Verified provider currently supports one adult only")
        if not self.classes or not set(self.classes) <= {"standard", "first"}:
            raise ValueError("Invalid seat classes")

@dataclass(frozen=True)
class Train:
    number: str
    family: str
    departure: str
    arrival: str
    start: time
    end: time
    standard: str
    first: str

class CardParser(HTMLParser):
    """Only parse known visible card fields; unknown availability stays unknown."""
    def __init__(self):
        super().__init__()
        self.cards = []
        self.card = None
        self.stack = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if tag == "li" and "tckList" in classes:
            if self.card is not None:
                raise ValueError("Nested train card")
            self.card = {"family": "", "number": "", "route": "", "standard": "", "first": ""}
            self.stack = []
        if self.card is None:
            return
        parent = self.stack[-1][1] if self.stack else None
        field = parent
        if tag == "h3":
            field = "route"
        elif "blind" in classes and parent is None:
            field = "family"
        elif "num" in classes:
            field = "number"
        elif "price_box" in classes:
            field = "standard" if "gen" in classes else "first" if "spe" in classes else None
        if tag not in {"br", "img", "input", "hr", "meta", "link"}:
            self.stack.append((tag, field))

    def handle_data(self, data):
        if self.card is not None and self.stack and self.stack[-1][1]:
            self.card[self.stack[-1][1]] += data

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == "li":
            self.cards.append(self.card)
            self.card = None
            self.stack = []
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

def availability(text):
    if "입석" in text or "예약대기" in text:
        return "unavailable"
    if "매진" in text and "매진임박" not in text:
        return "sold_out"
    if re.search(r"[0-9,]+원", text) and ("일반실" in text or "특실" in text):
        return "available"
    return "unknown"

def parse_cards(html):
    parser = CardParser()
    parser.feed(html)
    if parser.card is not None:
        raise ValueError("Incomplete card")
    result = []
    for card in parser.cards:
        route = re.fullmatch(r"\s*(.+?)\s*→\s*(.+?)\s*\((\d{2}:\d{2})\s*~\s*(\d{2}:\d{2})\)\s*", card["route"])
        if not route or not card["number"].strip().isdigit() or not card["family"].strip():
            raise ValueError("Korail result structure changed; do not report sold out")
        departure, arrival, start, end = route.groups()
        result.append(Train(str(int(card["number"])), card["family"].strip(), departure.strip(),
                            arrival.strip(), time.fromisoformat(start), time.fromisoformat(end),
                            availability(card["standard"]), availability(card["first"])))
    return result

def matching_trains(watch, queried_day, trains):
    if queried_day != watch.day:
        raise ValueError("Query date does not match watch")
    return [train for train in trains if train.family.startswith("KTX")
            and train.departure == watch.departure and train.arrival == watch.arrival
            and watch.start <= train.start <= watch.end
            and (not watch.train_numbers or train.number in watch.train_numbers)
            and any(getattr(train, seat) == "available" for seat in watch.classes)]

class PushError(Exception):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable

def post_expo(endpoint, payload, access_token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = "Bearer " + access_token
    req = Request("https://exp.host/--/api/v2/push/" + endpoint,
                  data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        raise PushError("HTTP_" + str(error.code), error.code == 429 or error.code >= 500) from None
    except (URLError, TimeoutError):
        raise PushError("NETWORK_ERROR", True) from None

def send_alert(token, watch, trains, alert_id, transport=post_expo):
    if not re.fullmatch(r"(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]", token):
        raise ValueError("Invalid Expo push token")
    matches = matching_trains(watch, watch.day, trains)
    matches = sorted({(t.number, t.start): t for t in matches}.values(), key=lambda t: (t.start, t.number))
    if not matches:
        raise ValueError("No verified matching available seats")
    first = matches[0]
    payload = {
        "to": token, "title": "WayBackHome 좌석 발견",
        "body": f"{watch.day:%m/%d} {watch.departure}→{watch.arrival} "
                f"{watch.start:%H:%M}~{watch.end:%H:%M} 출발, 총 {len(matches)}편 예매 가능 "
                f"(첫 출발 {first.start:%H:%M})",
        "sound": "default", "channelId": "seat-alerts", "priority": "high", "ttl": 300,
        "data": {"alertId": alert_id, "kind": "seat_available", "date": watch.day.isoformat(),
                 "trainNumber": first.number, "departureTime": first.start.strftime("%H:%M"),
                 "trainCount": len(matches)},
    }
    response = transport("send", payload)
    ticket = response.get("data", {})
    if not isinstance(ticket, dict) or ticket.get("status") != "ok" or not ticket.get("id"):
        details = ticket.get("details", {}) if isinstance(ticket, dict) else {}
        raise PushError(details.get("error", "EXPO_TICKET_ERROR"))
    return ticket["id"]

def check_receipt(ticket_id, transport=post_expo):
    receipt = transport("getReceipts", {"ids": [ticket_id]}).get("data", {}).get(ticket_id)
    if receipt is None:
        return "pending"
    if receipt.get("status") != "ok":
        raise PushError(receipt.get("details", {}).get("error", "EXPO_RECEIPT_ERROR"))
    return "provider_accepted"  # This is NOT proof that the phone received it.
