import json
import csv
import os
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from settings_store import get_sc_limit_percent

IST = ZoneInfo("Asia/Kolkata")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DAILY_DIR = os.path.join(DATA_DIR, "daily")
STRATEGY_DIR_NAME = "strategy"
os.makedirs(DAILY_DIR, exist_ok=True)

# Strategy version: strong SC1/SC2/SC3 + RC + immediate TC.
STRATEGY_VERSION = "V4_DYNAMIC_SC_STRENGTH_RC_TC"

_LOCK = threading.Lock()
_STATE = {}
_LOADED = False
_CURRENT_DAY = None

CSV_FIELDS = [
    "trade_id", "setup_id", "strategy_version", "created_at", "updated_at",
    "symbol", "interval", "direction", "pattern", "setup_label", "status", "result",
    "breakout_level", "level_name", "entry_price", "entry_trigger_rule", "sl", "risk", "target",
    "trigger_time", "trigger_time_display", "entry_execution_source", "entry_candle_close",
    "sl_activation", "exit_time", "exit_price", "exit_reason", "r_multiple", "trigger_index",
    "setup_candles", "confirmation_candle", "reversal_candle", "trigger_candle",
    "sc_strength", "setup_quality", "max_wick_body_ratio", "sc_wick_limit_percent", "notes"
]

SETUP_FIELDS = [
    "setup_id", "strategy_version", "symbol", "interval", "direction", "pattern", "setup_label",
    "outcome", "failure_reason", "breakout_level", "level_name", "reference_sl",
    "pattern_end_time", "pattern_end_time_display", "trigger_time", "trigger_time_display",
    "trigger_crossed", "setup_candles", "confirmation_candle", "reversal_candle", "trigger_candle",
    "sc_strength", "setup_quality", "max_wick_body_ratio", "sc_wick_limit_percent"
]


def current_day():
    return datetime.now(IST).date()


def now_iso():
    return datetime.now(IST).isoformat()


def _day(value=None):
    if value is None:
        return current_day()
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date()
    except Exception:
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except Exception:
            return current_day()


def daily_dir(day=None):
    day = day or current_day()
    path = os.path.join(DAILY_DIR, day.strftime("%Y-%m-%d"), STRATEGY_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def daily_csv_path(day=None):
    return os.path.join(daily_dir(day), "trades.csv")


def daily_setups_path(day=None):
    return os.path.join(daily_dir(day), "setups.csv")


def _date_range(date_from=None, date_to=None):
    start = _day(date_from) if date_from else current_day()
    end = _day(date_to) if date_to else start
    if start > end:
        start, end = end, start
    if (end - start).days > 3660:
        start = end - timedelta(days=3660)
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _encode(row):
    out = dict(row)
    for key in ("setup_candles", "confirmation_candle", "reversal_candle", "trigger_candle", "sc_strength", "notes"):
        out[key] = json.dumps(out.get(key), ensure_ascii=False)
    return out


def _decode(row):
    trade = dict(row)
    # Backward compatibility with older strategy CSVs.
    if not trade.get("reversal_candle") and trade.get("confirmation_candle"):
        trade["reversal_candle"] = trade.get("confirmation_candle")

    for key in ("setup_candles", "confirmation_candle", "reversal_candle", "trigger_candle", "sc_strength", "notes"):
        try:
            default = "[]" if key in ("setup_candles", "sc_strength", "notes") else "null"
            trade[key] = json.loads(trade.get(key) or default)
        except Exception:
            trade[key] = [] if key in ("setup_candles", "sc_strength", "notes") else None

    for key in (
        "breakout_level", "entry_price", "sl", "risk", "target", "entry_candle_close",
        "exit_price", "r_multiple", "reference_sl", "max_wick_body_ratio", "sc_wick_limit_percent"
    ):
        if trade.get(key) not in (None, ""):
            try:
                trade[key] = float(trade[key])
            except (TypeError, ValueError):
                pass
    if trade.get("trigger_index") not in (None, ""):
        try:
            trade["trigger_index"] = int(trade["trigger_index"])
        except (TypeError, ValueError):
            pass
    return trade


def _migrate_legacy_locked():
    legacy_dir = os.path.join(DATA_DIR, "strategy_trades_daily")
    marker = os.path.join(DATA_DIR, ".strategy_migrated_v2")
    if os.path.exists(marker):
        return
    if os.path.isdir(legacy_dir):
        for name in os.listdir(legacy_dir):
            if not name.endswith(".csv") or not name.startswith("strategy_trades_"):
                continue
            day_text = name[len("strategy_trades_"):-4]
            try:
                day = datetime.strptime(day_text, "%Y-%m-%d").date()
            except ValueError:
                continue
            target = daily_csv_path(day)
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                import shutil
                shutil.copy2(os.path.join(legacy_dir, name), target)
            except OSError:
                pass
    if os.path.isdir(legacy_dir):
        legacy_archive = os.path.join(DAILY_DIR, "_legacy")
        os.makedirs(legacy_archive, exist_ok=True)
        try:
            import shutil
            target = os.path.join(legacy_archive, "strategy_trades_daily")
            if not os.path.exists(target):
                shutil.move(legacy_dir, target)
        except OSError:
            pass
    try:
        open(marker, "w", encoding="utf-8").write(now_iso())
    except OSError:
        pass


def _read_trades_file(day):
    path = daily_csv_path(day)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [_decode(row) for row in csv.DictReader(f)]


def _save_csv_locked():
    path = daily_csv_path(current_day())
    tmp = path + ".tmp"
    items = sorted(_STATE.values(), key=lambda x: x.get("created_at", ""))
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for trade in items:
            row = _encode(trade)
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})
    os.replace(tmp, path)


def _save_setups(day, setups):
    path = daily_setups_path(day)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SETUP_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for setup in setups:
            row = _encode(setup)
            writer.writerow({field: row.get(field, "") for field in SETUP_FIELDS})
    os.replace(tmp, path)


def _ensure_day_locked():
    global _CURRENT_DAY, _STATE, _LOADED
    _migrate_legacy_locked()
    day = current_day()
    if _CURRENT_DAY == day and _LOADED:
        return
    _CURRENT_DAY = day
    _STATE = {t["trade_id"]: t for t in _read_trades_file(day) if t.get("trade_id")}
    _LOADED = True


def _load():
    _ensure_day_locked()


def _append(record):
    _ensure_day_locked()
    _STATE[record["trade_id"]] = record
    _save_csv_locked()


def _date_range_all():
    days = []
    if os.path.isdir(DAILY_DIR):
        for name in os.listdir(DAILY_DIR):
            try:
                d = datetime.strptime(name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if os.path.isdir(os.path.join(DAILY_DIR, name, STRATEGY_DIR_NAME)):
                days.append(d)
    return sorted(days)


def all_trades(limit=5000, date_from=None, date_to=None):
    with _LOCK:
        items = []
        if date_from or date_to:
            for day in _date_range(date_from, date_to):
                items.extend(_read_trades_file(day))
        else:
            for day in _date_range_all():
                items.extend(_read_trades_file(day))
        items.sort(key=lambda x: x.get("trigger_time") or x.get("created_at") or "", reverse=True)
        return items[:limit]


def available_dates():
    result = []
    if os.path.isdir(DAILY_DIR):
        for name in os.listdir(DAILY_DIR):
            if os.path.isdir(os.path.join(DAILY_DIR, name, STRATEGY_DIR_NAME)):
                try:
                    datetime.strptime(name, "%Y-%m-%d")
                    result.append(name)
                except ValueError:
                    pass
    return sorted(result, reverse=True)


def storage_root():
    return os.path.relpath(DAILY_DIR, BASE_DIR).replace(os.sep, "/")


def clear_trades():
    global _STATE, _LOADED, _CURRENT_DAY
    with _LOCK:
        _CURRENT_DAY = current_day()
        _STATE = {}
        _LOADED = True
        for path in (daily_csv_path(_CURRENT_DAY), daily_setups_path(_CURRENT_DAY)):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def _key(c):
    return c.get("time") or c.get("time_display")


def _candle_day(c):
    value = _key(c)
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).date()
    except Exception:
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except Exception:
            return None


def _wick_metrics(candle, limit_percent=None):
    """Return strong-candle metrics using the current editable SC wick/body limit."""
    o = float(candle["open"])
    h = float(candle["high"])
    l = float(candle["low"])
    close = float(candle["close"])
    body = abs(close - o)
    upper = max(0.0, h - max(o, close))
    lower = max(0.0, min(o, close) - l)
    total = upper + lower
    ratio = float("inf") if body <= 0 else total / body
    limit_percent = get_sc_limit_percent() if limit_percent is None else float(limit_percent)
    return {
        "body": body,
        "upper_wick": upper,
        "lower_wick": lower,
        "total_wick": total,
        "wick_body_ratio": ratio,
        "wick_body_percent": None if body <= 0 else ratio * 100.0,
        "limit_percent": limit_percent,
        "strong": body > 0 and ratio * 100.0 <= limit_percent,
    }


def _strong_setup_filter(candles, limit_percent=None):
    limit_percent = get_sc_limit_percent() if limit_percent is None else float(limit_percent)
    metrics = []
    for idx, candle in enumerate(candles, start=1):
        m = _wick_metrics(candle, limit_percent)
        metrics.append({
            "candle": f"SC{idx}",
            "body": round(m["body"], 6),
            "upper_wick": round(m["upper_wick"], 6),
            "lower_wick": round(m["lower_wick"], 6),
            "total_wick": round(m["total_wick"], 6),
            "wick_body_ratio": None if m["wick_body_ratio"] == float("inf") else round(m["wick_body_ratio"], 6),
            "wick_body_percent": None if m["wick_body_percent"] is None else round(m["wick_body_percent"], 2),
            "strong": bool(m["strong"]),
            "limit_percent": round(limit_percent, 2),
        })
    valid = all(item["strong"] for item in metrics)
    max_ratio = max((item["wick_body_ratio"] for item in metrics if item["wick_body_ratio"] is not None), default=None)
    return valid, metrics, max_ratio


def _make_setup(symbol, interval, candles, i, direction, sc_limit_percent=None):
    """Build SC1 → SC2 → SC3 → RC. TC is the immediate next completed candle."""
    if i + 4 > len(candles):
        return None

    sc1, sc2, sc3, rc = candles[i:i + 4]
    types = [sc1.get("type"), sc2.get("type"), sc3.get("type"), rc.get("type")]

    if direction == "LONG":
        if types != ["GREEN", "GREEN", "GREEN", "RED"]:
            return None
        pattern = "SC1 G → SC2 G → SC3 G → RC R → TC"
        setup_label = "3 Green Setup → Red Reversal"
        level_name = "4-Candle Highest High"
        level = max(float(x["high"]) for x in (sc1, sc2, sc3, rc))
        sl = float(rc["low"])
        pattern_code = "G3R1"
    else:
        if types != ["RED", "RED", "RED", "GREEN"]:
            return None
        pattern = "SC1 R → SC2 R → SC3 R → RC G → TC"
        setup_label = "3 Red Setup → Green Reversal"
        level_name = "4-Candle Lowest Low"
        level = min(float(x["low"]) for x in (sc1, sc2, sc3, rc))
        sl = float(rc["high"])
        pattern_code = "R3G1"

    limit_percent = get_sc_limit_percent() if sc_limit_percent is None else float(sc_limit_percent)
    strong, sc_strength, max_ratio = _strong_setup_filter([sc1, sc2, sc3], limit_percent)
    weak = [m for m in sc_strength if not m["strong"]]
    failure_reason = ""
    if weak:
        failure_reason = "; ".join(
            f'{m["candle"]} weak ({m["wick_body_percent"]:.1f}% > {limit_percent:.1f}%)'
            if m.get("wick_body_percent") is not None
            else f'{m["candle"]} invalid (zero body)'
            for m in weak
        )

    return {
        "setup_id": f"{STRATEGY_VERSION}|{symbol}|{interval}|{_key(sc1)}|{direction}",
        "strategy_version": STRATEGY_VERSION,
        "symbol": symbol,
        "interval": interval,
        "direction": direction,
        "pattern": pattern,
        "pattern_code": pattern_code,
        "setup_label": setup_label,
        "pattern_candles": [sc1, sc2, sc3, rc],
        "setup_candles": [sc1, sc2, sc3],
        "confirmation_candle": rc,  # legacy field compatibility
        "reversal_candle": rc,
        "sc_strength": sc_strength,
        "setup_quality": "PERFECT_SETUP" if strong else "FAILED_WEAK_SC",
        "max_wick_body_ratio": max_ratio,
        "sc_wick_limit_percent": limit_percent,
        "failure_reason": failure_reason,
        "breakout_level": round(level, 2),
        "level_name": level_name,
        "reference_sl": round(sl, 2),
        "pattern_end_index": i + 3,
        "trigger_index": i + 4,
        "pattern_end_time": _key(rc),
        "trigger_rule": "IMMEDIATE_NEXT_TRIGGER_CANDLE_ONLY",
        "outcome": "WAITING_FOR_TRIGGER_CANDLE",
    }


def _trade_for_setup(setup_id):
    return next((t for t in _STATE.values() if t.get("setup_id") == setup_id), None)


def _new_trade(setup, trigger_candle, trigger_index):
    entry = float(setup["breakout_level"])
    sl = float(setup["reference_sl"])
    risk = entry - sl if setup["direction"] == "LONG" else sl - entry
    if risk <= 0:
        return None

    target = entry + 2 * risk if setup["direction"] == "LONG" else entry - 2 * risk
    trade_id = f"{setup['setup_id']}|TRIGGER|{_key(trigger_candle)}"
    return {
        "trade_id": trade_id,
        "setup_id": setup["setup_id"],
        "strategy_version": STRATEGY_VERSION,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "symbol": setup["symbol"],
        "interval": setup["interval"],
        "direction": setup["direction"],
        "pattern": setup["pattern"],
        "setup_label": setup["setup_label"],
        "status": "PUNCHED",
        "result": None,
        "setup_candles": setup["setup_candles"],
        "confirmation_candle": setup["reversal_candle"],
        "reversal_candle": setup["reversal_candle"],
        "trigger_candle": trigger_candle,
        "sc_strength": setup["sc_strength"],
        "setup_quality": setup["setup_quality"],
        "max_wick_body_ratio": setup["max_wick_body_ratio"],
        "sc_wick_limit_percent": setup["sc_wick_limit_percent"],
        "breakout_level": setup["breakout_level"],
        "level_name": setup["level_name"],
        "entry_price": round(entry, 2),
        "entry_trigger_rule": "IMMEDIATE_TC_CROSS",
        "sl": round(sl, 2),
        "risk": round(risk, 2),
        "target": round(target, 2),
        "trigger_time": _key(trigger_candle),
        "trigger_time_display": trigger_candle.get("time_display"),
        "entry_execution_source": "CURRENT_FEED_OHLC_THEORETICAL_LEVEL",
        "entry_candle_close": trigger_candle.get("close"),
        "sl_activation": None,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "r_multiple": None,
        "trigger_index": trigger_index,
        "notes": [
            f'SC1, SC2 and SC3 passed the mandatory strong-candle filter: total upper + lower wick <= {setup["sc_wick_limit_percent"]:.1f}% of body for every SC.', 
            "RC is exempt from the 40% wick/body rule; RC only needs to be the opposite color of SC1-SC3.",
            "TC is the immediate next completed candle after RC. No later candle may trigger this setup.",
            "OHLC cannot determine an exact tick; entry is recorded at the crossed setup level.",
        ],
    }


def _entry_close_invalidates(trade):
    close = float(trade["entry_candle_close"])
    sl = float(trade["sl"])
    return close < sl if trade["direction"] == "LONG" else close > sl


def _evaluate_active(trade, later_candles):
    direction = trade["direction"]
    sl = float(trade["sl"])
    target = float(trade["target"])

    for c in later_candles:
        hi, lo = float(c["high"]), float(c["low"])
        hit_sl = lo <= sl if direction == "LONG" else hi >= sl
        hit_target = hi >= target if direction == "LONG" else lo <= target

        if hit_sl and hit_target:
            return c, "AMBIGUOUS_BOTH_HIT", None, "Both SL and target were touched in the same completed candle; OHLC cannot establish intrabar order."
        if hit_target:
            return c, "TARGET_HIT", target, "1:2 target reached after SL activation."
        if hit_sl:
            return c, "SL_HIT", sl, "Stop-loss reached after SL activation."

    return None, None, None, None


def evaluate(symbol, interval, candles, validity_candles=1, selected=True, sc_limit_percent=None, backtest_date=None):
    """Evaluate SC1 → SC2 → SC3 → RC → immediate TC using completed candles only."""
    del validity_candles

    with _LOCK:
        _load()
        target_day = _day(backtest_date) if backtest_date else current_day()
        is_backtest = backtest_date is not None
        # Backtests are isolated to the requested IST calendar date.
        if backtest_date:
            candles = [c for c in candles if _candle_day(c) == target_day]
        if not selected:
            return {"trades": [], "setups": [], "message": "Symbol is not selected for strategy evaluation."}
        if len(candles) < 5:
            return {
                "trades": [],
                "setups": [],
                "message": "Waiting for five completed candles: SC1 + SC2 + SC3 + RC + TC.",
            }

        active_limit = get_sc_limit_percent() if sc_limit_percent is None else max(0.01, float(sc_limit_percent))
        working_trades = {} if is_backtest else _STATE
        setups = []
        for i in range(0, len(candles) - 3):
            # Every setup must be entirely inside the selected backtest/live day.
            if any(_candle_day(c) != target_day for c in candles[i:i + 4]):
                continue

            for direction in ("LONG", "SHORT"):
                setup = _make_setup(symbol, interval, candles, i, direction, active_limit)
                if not setup:
                    continue

                if setup.get("setup_quality") != "PERFECT_SETUP":
                    setup["outcome"] = "FAILED_WEAK_SC"
                    setup["trigger_crossed"] = False
                    setup["trigger_candle"] = None
                    setup["trigger_time"] = None
                    setup["trigger_time_display"] = None
                    setups.append(setup)
                    continue

                trigger_index = setup["trigger_index"]
                if trigger_index >= len(candles):
                    setup["outcome"] = "WAITING_FOR_TRIGGER_CANDLE"
                    setups.append(setup)
                    continue

                trigger = candles[trigger_index]
                if direction == "LONG":
                    crossed = float(trigger["high"]) > float(setup["breakout_level"])
                else:
                    crossed = float(trigger["low"]) < float(setup["breakout_level"])

                setup["trigger_candle"] = trigger
                setup["trigger_crossed"] = bool(crossed)
                setup["trigger_time"] = _key(trigger)
                setup["trigger_time_display"] = trigger.get("time_display")

                if not crossed:
                    # Valid strong setup, but the only permitted trigger candle failed.
                    setup["outcome"] = "FAILED_NEXT_TRIGGER_CANDLE"
                    setup["failure_reason"] = "TC did not cross the 4-candle breakout/breakdown level; no later candle may trigger this setup."
                    setups.append(setup)
                    continue

                setup["outcome"] = "PUNCHED"
                setups.append(setup)

                if any(t.get("setup_id") == setup["setup_id"] for t in working_trades.values()):
                    continue

                trade = _new_trade(setup, trigger, trigger_index)
                if not trade:
                    setup["outcome"] = "FAILED_INVALID_RISK"
                    setup["trigger_crossed"] = True
                    setup["failure_reason"] = "Breakout/breakdown was crossed, but the calculated Entry-to-SL risk was not positive; no trade was created."
                    continue

                if _entry_close_invalidates(trade):
                    trade["status"] = "CLOSED"
                    trade["result"] = "SYSTEMATIC_SL"
                    trade["exit_reason"] = "TC closed beyond the reference SL. Intrabar SL is not counted before TC closes."
                    trade["exit_time"] = _key(trigger)
                    trade["exit_price"] = round(float(trigger["close"]), 2)
                    trade["r_multiple"] = -1.0
                else:
                    trade["status"] = "ACTIVE"
                    trade["sl_activation"] = trigger.get("closed_at") or _key(trigger)
                    trade["notes"].append("SL becomes active only after TC closes and validates the entry candle.")

                if is_backtest:
                    working_trades[trade["trade_id"]] = trade
                else:
                    _append(trade)

        # Persist only valid strong setups. Weak SC formations are intentionally
        # invisible to the setup audit, dashboard and strategy journal.
        if not is_backtest:
            existing_setups = []
            try:
                setup_path = daily_setups_path(current_day())
                if os.path.exists(setup_path):
                    with open(setup_path, "r", encoding="utf-8-sig", newline="") as sf:
                        existing_setups = list(csv.DictReader(sf))
            except Exception:
                existing_setups = []
            setup_map = {row.get("setup_id"): row for row in existing_setups if row.get("setup_id")}
            for setup in setups:
                setup_map[setup.get("setup_id")] = setup
            _save_setups(current_day(), list(setup_map.values()))

        # Resolve active trades only with candles AFTER their TC.
        for trade in list(working_trades.values()):
            if trade.get("symbol") != symbol or trade.get("interval") != interval or trade.get("status") != "ACTIVE":
                continue

            trigger_time = trade.get("trigger_time")
            later = []
            passed = False
            for c in candles:
                if passed:
                    later.append(c)
                if _key(c) == trigger_time:
                    passed = True

            exit_c, result, exit_price, reason = _evaluate_active(trade, later)
            if result:
                trade["status"] = "CLOSED"
                trade["result"] = result
                trade["exit_reason"] = reason
                trade["exit_time"] = _key(exit_c)
                trade["exit_price"] = round(float(exit_price), 2) if exit_price is not None else None
                trade["r_multiple"] = 2.0 if result == "TARGET_HIT" else -1.0 if result == "SL_HIT" else None
                trade["updated_at"] = now_iso()
                if is_backtest:
                    working_trades[trade["trade_id"]] = trade
                else:
                    _append(trade)

        trades = [t for t in working_trades.values() if t.get("symbol") == symbol and t.get("interval") == interval]
        trades.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {
            "trades": trades,
            "setups": setups,
            "message": (f'Backtest date {target_day.isoformat()}: SC1 → SC2 → SC3 → RC → immediate TC. All three SC candles must satisfy the current <= {active_limit:.1f}% total-wick/body rule.' if is_backtest else f'Strategy evaluated using SC1 → SC2 → SC3 → RC → immediate TC. All three SC candles must satisfy the current <= {active_limit:.1f}% total-wick/body rule.'),
        }
