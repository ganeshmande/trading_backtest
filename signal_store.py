import csv
import json
import os
import threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DAILY_DIR = os.path.join(DATA_DIR, "daily")
IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()

CSV_FIELDS = [
    "event_id", "arrival_time", "arrival_time_display", "symbol", "name",
    "interval", "category", "index_membership", "index_tags", "signal",
    "direction", "pattern", "signal_candle_time", "signal_candle_time_ist",
    "signal_candle_closed_at", "signal_candle_closed_at_display",
    "signal_open", "signal_high", "signal_low", "signal_close",
]
for i in range(1, 8):
    CSV_FIELDS += [
        f"c{i}_type", f"c{i}_time", f"c{i}_closed_at",
        f"c{i}_open", f"c{i}_high", f"c{i}_low", f"c{i}_close", f"c{i}_wick_body_percent"
    ]


def _day_from_value(value=None):
    if not value:
        return datetime.now(IST).date()
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date()
    except Exception:
        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return datetime.now(IST).date()


def current_day():
    return datetime.now(IST).date()


def day_dir(day):
    day = day if isinstance(day, date) else date.fromisoformat(str(day))
    path = os.path.join(DAILY_DIR, day.strftime("%Y-%m-%d"))
    os.makedirs(path, exist_ok=True)
    return path


def daily_jsonl_path(day):
    return os.path.join(day_dir(day), "signals.jsonl")


def daily_csv_path(day):
    return os.path.join(day_dir(day), "signals.csv")


def _date_range(date_from=None, date_to=None):
    start = _day_from_value(date_from) if date_from else current_day()
    end = _day_from_value(date_to) if date_to else start
    if start > end:
        start, end = end, start
    # Safety cap for accidental huge ranges.
    if (end - start).days > 3660:
        start = end - timedelta(days=3660)
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _csv_row(event):
    row = {k: "" for k in CSV_FIELDS}
    for key in CSV_FIELDS:
        if key in event and not isinstance(event[key], (dict, list)):
            row[key] = event.get(key, "")
    row["index_tags"] = "; ".join(event.get("index_tags", []) or [])
    candle = event.get("signal_candle") or {}
    row.update({
        "signal_open": candle.get("open", ""), "signal_high": candle.get("high", ""),
        "signal_low": candle.get("low", ""), "signal_close": candle.get("close", ""),
    })
    for i, c in enumerate((event.get("seven_candles") or [])[:7], 1):
        row[f"c{i}_type"] = c.get("type", "")
        row[f"c{i}_time"] = c.get("time_display", c.get("time", ""))
        row[f"c{i}_closed_at"] = c.get("closed_at_display", c.get("closed_at", ""))
        row[f"c{i}_open"] = c.get("open", "")
        row[f"c{i}_high"] = c.get("high", "")
        row[f"c{i}_low"] = c.get("low", "")
        row[f"c{i}_close"] = c.get("close", "")
        pct = c.get("wick_body_percent", "")
        if pct in (None, ""):
            try:
                body = abs(float(c.get("close")) - float(c.get("open")))
                wick = (float(c.get("high")) - max(float(c.get("open")), float(c.get("close")))) + (min(float(c.get("open")), float(c.get("close"))) - float(c.get("low")))
                pct = "" if body <= 0 else round((wick / body) * 100.0, 2)
            except (TypeError, ValueError):
                pct = ""
        row[f"c{i}_wick_body_percent"] = pct
    return row


def _write_csv(day, events):
    path = daily_csv_path(day)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for event in sorted(events, key=lambda x: x.get("arrival_time", ""), reverse=True):
            writer.writerow(_csv_row(event))
    os.replace(tmp, path)


def _read_jsonl(day):
    path = daily_jsonl_path(day)
    events = []
    if not os.path.exists(path):
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _migrate_legacy_locked():
    """One-time migration of old flat signal history into the date-wise archive."""
    marker = os.path.join(DATA_DIR, ".signals_migrated_v1")
    if os.path.exists(marker):
        return
    legacy = os.path.join(DATA_DIR, "signals.jsonl")
    migrated = 0
    if os.path.exists(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    day = _day_from_value(event.get("arrival_time") or event.get("signal_candle_time"))
                    existing = _read_jsonl(day)
                    if any(x.get("event_id") == event.get("event_id") for x in existing):
                        continue
                    with open(daily_jsonl_path(day), "a", encoding="utf-8") as out:
                        out.write(json.dumps(event, ensure_ascii=False) + "\n")
                    existing.append(event)
                    _write_csv(day, existing)
                    migrated += 1
        except OSError:
            pass
    # If only the old CSV exists, preserve its detailed rows in a legacy archive file rather than losing data.
    old_csv = os.path.join(DATA_DIR, "history.csv")
    if os.path.exists(old_csv) and not migrated:
        legacy_copy = os.path.join(DATA_DIR, "daily", "_legacy", "history_legacy.csv")
        os.makedirs(os.path.dirname(legacy_copy), exist_ok=True)
        try:
            if not os.path.exists(legacy_copy):
                import shutil
                shutil.copy2(old_csv, legacy_copy)
        except OSError:
            pass
    # Move old flat files into the central archive so the live data root remains systematic.
    legacy_archive = os.path.join(DAILY_DIR, "_legacy")
    os.makedirs(legacy_archive, exist_ok=True)
    for legacy_name in ("signals.jsonl", "history.csv"):
        legacy_path = os.path.join(DATA_DIR, legacy_name)
        if os.path.exists(legacy_path):
            try:
                import shutil
                target = os.path.join(legacy_archive, legacy_name)
                if not os.path.exists(target): shutil.move(legacy_path, target)
            except OSError:
                pass
    try:
        open(marker, "w", encoding="utf-8").write(datetime.now(IST).isoformat())
    except OSError:
        pass


def _ensure_files():
    os.makedirs(DAILY_DIR, exist_ok=True)
    _migrate_legacy_locked()
    day = current_day()
    daily_jsonl_path(day)
    daily_csv_path(day)


def _all_days():
    days=[]
    if os.path.isdir(DAILY_DIR):
        for name in os.listdir(DAILY_DIR):
            try: d=date.fromisoformat(name)
            except ValueError: continue
            if os.path.isdir(os.path.join(DAILY_DIR,name)): days.append(d)
    return sorted(days)

def read_events(limit=500, date_from=None, date_to=None):
    _ensure_files()
    events = []
    with _LOCK:
        days = _all_days() if not date_from and not date_to else list(_date_range(date_from, date_to))
        for day in days:
            events.extend(_read_jsonl(day))
    events.sort(key=lambda x: x.get("arrival_time", ""), reverse=True)
    return events[:max(1, int(limit))]


def append_if_new(event):
    _ensure_files()
    day = _day_from_value(event.get("arrival_time") or event.get("signal_candle_time"))
    with _LOCK:
        events = _read_jsonl(day)
        key = (event.get("symbol"), event.get("interval"), event.get("signal_candle_time"), event.get("direction"))
        if any((x.get("symbol"), x.get("interval"), x.get("signal_candle_time"), x.get("direction")) == key for x in events):
            _write_csv(day, events)
            return False
        with open(daily_jsonl_path(day), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        events.append(event)
        _write_csv(day, events)
        return True


def sync_csv(events=None):
    _ensure_files()
    if events is None:
        events = read_events(5000)
    grouped = {}
    for event in events:
        grouped.setdefault(_day_from_value(event.get("arrival_time") or event.get("signal_candle_time")), []).append(event)
    with _LOCK:
        for day, rows in grouped.items():
            _write_csv(day, rows)


def available_dates():
    _ensure_files()
    result = []
    if os.path.isdir(DAILY_DIR):
        for name in os.listdir(DAILY_DIR):
            try:
                d = date.fromisoformat(name)
            except ValueError:
                continue
            if os.path.isdir(os.path.join(DAILY_DIR, name)):
                result.append(name)
    return sorted(result, reverse=True)


def storage_root():
    return os.path.relpath(DAILY_DIR, BASE_DIR).replace(os.sep, "/")


def clear_events():
    _ensure_files()
    day = current_day()
    with _LOCK:
        for path in (daily_jsonl_path(day), daily_csv_path(day)):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
