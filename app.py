from flask import Flask, jsonify, render_template, request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time, threading

from data_provider import MarketDataProvider
from signal_store import append_if_new, read_events, clear_events, sync_csv, available_dates as signal_dates, storage_root as signal_storage_root
from strategy_engine import evaluate as evaluate_strategy, all_trades as strategy_trades, clear_trades as clear_strategy_trades, available_dates as strategy_dates, storage_root as strategy_storage_root
from settings_store import get_settings, update_settings, get_sc_limit_percent
from fetcher import start_job as start_data_fetch, status as data_fetch_status
from historical_store import coverage as data_coverage, dates as data_dates, query as market_data_query

app = Flask(__name__)
provider = MarketDataProvider()
IST = ZoneInfo("Asia/Kolkata")

INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d"]
DASHBOARD_HOLD_SECONDS = 300

INDICES = ["NIFTY50", "SENSEX", "BANKNIFTY"]

NIFTY_50 = [
    "360ONE", "ABCAPITAL", "ABB", "ADANIENT", "ADANIPORTS",
    "ATHERENERG", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BANDHANBNK",
    "BANKBARODA", "BANKINDIA", "BEL", "BHARTIARTL", "BIOCON",
    "BSE", "CANBK", "CDSL", "CGPOWER", "CIPLA", "COALINDIA",
    "DELHIVERY", "DLF", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GODFRYPHLP", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDPETRO", "HINDUNILVR",
    "HINDZINC", "ICICIBANK", "INDUSINDBK", "INFY", "ITC",
    "JIOFIN", "JSWENERGY", "JSWSTEEL", "KOTAKBANK", "LTF", "LT",
    "LUPIN", "M&M", "MARUTI", "MAXHEALTH", "MCX", "MOTILALOFS",
    "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "ONGC", "PERSISTENT",
    "PNB", "POWERGRID", "RELIANCE", "SAIL", "SBILIFE", "SBIN",
    "SHRIRAMFIN", "SIEMENS", "SUNPHARMA", "SUZLON", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT",
    "UNITDSPR", "ULTRACEMCO", "VEDL",
]

NIFTY50_STOCKS = {
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO", "INDUSINDBK",
    "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE",
    "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
    "WIPRO",
}

NIFTY100_ONLY_STOCKS = {
    "ABB", "BANKBARODA", "CANBK", "CGPOWER", "DLF", "HINDZINC",
    "PNB", "SIEMENS", "TATAMOTORS", "UNITDSPR", "VEDL",
}

# Extra index membership is intentionally data-driven. Add symbols to these sets
# when you want exact Nifty 150 / other index classification for this watchlist.
CUSTOM_INDEX_MEMBERS = {
    "NIFTY 150": set(),
}

DISPLAY_NAMES = {
    "NIFTY50": "NIFTY 50",
    "SENSEX": "SENSEX",
    "BANKNIFTY": "BANK NIFTY",
}
DISPLAY_NAMES.update({s: s for s in NIFTY_50})


def annotate_candle(candle):
    c = dict(candle or {})
    try:
        o, h, l, close = map(float, (c["open"], c["high"], c["low"], c["close"]))
        body = abs(close - o)
        upper = max(0.0, h - max(o, close))
        lower = max(0.0, min(o, close) - l)
        total = upper + lower
        pct = None if body <= 0 else (total / body) * 100.0
        c["body"] = round(body, 6); c["upper_wick"] = round(upper, 6); c["lower_wick"] = round(lower, 6); c["total_wick"] = round(total, 6)
        c["wick_body_percent"] = None if pct is None else round(pct, 2)
        c["wick_body_display"] = "DOJI / N/A" if pct is None else f"{pct:.1f}%"
    except (TypeError, ValueError, KeyError):
        c["wick_body_percent"] = None; c["wick_body_display"] = "N/A"
    return c

def annotate_candles(candles):
    return [annotate_candle(c) for c in (candles or [])]


def index_tags(symbol):
    if symbol == "NIFTY50":
        return ["NIFTY 50", "NIFTY 100", "NIFTY 200"]
    if symbol == "SENSEX":
        return ["SENSEX"]
    if symbol == "BANKNIFTY":
        return ["NIFTY BANK"]

    tags = []
    if symbol in NIFTY50_STOCKS:
        tags += ["NIFTY 50", "NIFTY 100", "NIFTY 200"]
    elif symbol in NIFTY100_ONLY_STOCKS:
        tags += ["NIFTY 100", "NIFTY 200"]
    for name, symbols in CUSTOM_INDEX_MEMBERS.items():
        if symbol in symbols and name not in tags:
            tags.append(name)
    return tags


def membership(symbol):
    if symbol in INDICES:
        return "INDEX"
    if symbol in NIFTY50_STOCKS:
        return "N50 & N100"
    if symbol in NIFTY100_ONLY_STOCKS:
        return "N100"
    return "OTHER"


def enrich_event(event):
    e = dict(event)
    e["index_membership"] = membership(e.get("symbol", ""))
    e["index_tags"] = index_tags(e.get("symbol", ""))
    e["category"] = "index" if e.get("symbol") in INDICES else "stock"
    e["seven_candles"] = annotate_candles(e.get("seven_candles") or [])
    e["sc_wick_limit_percent"] = get_sc_limit_percent()
    return e


def detect_signal(symbol, interval, candles):
    result = {
        "symbol": symbol,
        "name": DISPLAY_NAMES.get(symbol, symbol),
        "interval": interval,
        "category": "index" if symbol in INDICES else "stock",
        "index_membership": membership(symbol),
        "index_tags": index_tags(symbol),
        "candles": annotate_candles(candles),
        "signal": None, "direction": None, "pattern": None,
        "new_event": None,
    }
    if len(candles) < 7:
        return result

    candles = annotate_candles(candles)
    result["candles"] = candles
    types = [c["type"] for c in candles]
    c4, c5, c6, c7 = types[3:7]
    if c4 == c5 == c6 == "GREEN" and c7 == "RED":
        signal, direction, pattern = "3 GREEN → RED", "GREEN_TO_RED", "G G G R"
    elif c4 == c5 == c6 == "RED" and c7 == "GREEN":
        signal, direction, pattern = "3 RED → GREEN", "RED_TO_GREEN", "R R R G"
    else:
        return result

    # Dashboard/history signal eligibility uses the same editable SC strength
    # gate as Strategy Lab. RC (c7) is intentionally exempt.
    limit = get_sc_limit_percent()
    weak_sc = []
    for idx, candle in enumerate(candles[3:6], start=1):
        pct = candle.get("wick_body_percent")
        if pct is None or float(pct) > limit:
            weak_sc.append((idx, pct))
    if weak_sc:
        result["signal_rejected_reason"] = "; ".join(
            f"SC{i} weak ({pct:.1f}% > {limit:.1f}%)" if pct is not None else f"SC{i} invalid (zero body)"
            for i, pct in weak_sc
        )
        return result

    result.update(signal=signal, direction=direction, pattern=pattern)
    signal_candle = candles[-1]
    arrival = datetime.now(IST)
    event = {
        "event_id": f"{symbol}-{interval}-{signal_candle['time']}-{direction}",
        "arrival_time": arrival.isoformat(),
        "arrival_time_display": arrival.strftime("%d-%m-%Y %I:%M:%S %p"),
        "symbol": symbol, "name": DISPLAY_NAMES.get(symbol, symbol),
        "interval": interval, "category": result["category"],
        "index_membership": membership(symbol), "index_tags": index_tags(symbol),
        "signal": signal, "direction": direction, "pattern": pattern,
        "signal_candle_time": signal_candle["time"],
        "signal_candle_time_ist": signal_candle["time_display"],
        "signal_candle_closed_at": signal_candle["closed_at"],
        "signal_candle_closed_at_display": signal_candle["closed_at_display"],
        "signal_candle": signal_candle, "seven_candles": candles, "seven_types": types,
        "sc_wick_limit_percent": get_sc_limit_percent(),
        "explanation": f"Closed candles 4, 5 and 6 are {c4}, {c5}, {c6}; closed candle 7 is {c7}. Wick/body percentages are shown for study; the editable SC strength rule applies only to Strategy SC1-SC3. The running candle is excluded.",
    }
    return result, event


dashboard_signals = {}
dashboard_lock = threading.Lock()

def update_dashboard_hold(interval, events):
    now = time.time()
    with dashboard_lock:
        bucket = dashboard_signals.setdefault(interval, {})
        for symbol in [s for s, item in bucket.items() if item["expires_at"] <= now]:
            del bucket[symbol]
        for event in events:
            bucket[event["symbol"]] = {"event": event, "expires_at": now + DASHBOARD_HOLD_SECONDS}
        active = []
        for item in bucket.values():
            event = enrich_event(item["event"])
            remaining = max(0, int(item["expires_at"] - now))
            event["dashboard_remaining_seconds"] = remaining
            event["dashboard_remaining_minutes"] = round(remaining / 60, 1)
            active.append(event)
        return sorted(active, key=lambda x: x.get("arrival_time", ""), reverse=True)


@app.get("/")
def index():
    return render_template("index.html")

@app.get("/history")
def history():
    return render_template("history.html")

@app.get("/fetch-data")
def fetch_data_page():
    return render_template("fetch_data.html", symbols=NIFTY_50, indices=INDICES, intervals=INTERVALS, nifty50=sorted(NIFTY50_STOCKS), nifty100=sorted(NIFTY50_STOCKS | NIFTY100_ONLY_STOCKS))

@app.get("/strategy")
def strategy():
    return render_template("strategy.html", symbols=NIFTY_50, indices=INDICES, intervals=INTERVALS, nifty50=sorted(NIFTY50_STOCKS), nifty100=sorted(NIFTY50_STOCKS | NIFTY100_ONLY_STOCKS))


@app.get("/api/data/status")
def api_data_status():
    return jsonify({"success":True,"job":data_fetch_status(),"coverage":{i:data_coverage(NIFTY_50+INDICES,i) for i in INTERVALS},"dates":data_dates()[:120]})

@app.post("/api/data/fetch")
def api_data_fetch():
    payload=request.get_json(silent=True) or {}
    interval=str(payload.get("interval","1m"))
    if interval not in INTERVALS:return jsonify({"success":False,"error":"Invalid interval"}),400
    symbols=[str(x).upper() for x in (payload.get("symbols") or []) if str(x).strip()]
    if not symbols:return jsonify({"success":False,"error":"Select at least one instrument"}),400
    date_from=str(payload.get("date_from") or datetime.now(IST).date().isoformat())
    date_to=str(payload.get("date_to") or date_from)
    if date_from>date_to:return jsonify({"success":False,"error":"Date From cannot be after Date To"}),400
    ok=start_data_fetch(symbols,interval,date_from,date_to)
    if not ok:return jsonify({"success":False,"error":"A fetch job is already running"}),409
    return jsonify({"success":True,"message":"Historical data fetch started"})

@app.get("/api/data/query")
def api_data_query():
    from historical_store import query
    interval=request.args.get("interval","1m")
    symbols=[x.strip().upper() for x in request.args.get("symbols","").split(",") if x.strip()]
    rows=query(symbols,interval,request.args.get("date_from"),request.args.get("date_to"),min(int(request.args.get("limit","10000")),200000))
    return jsonify({"success":True,"count":len(rows),"rows":[{"symbol":r[0],"interval":r[1],"timestamp":r[2],"open":r[3],"high":r[4],"low":r[5],"close":r[6],"volume":r[7],"source":r[8]} for r in rows]})

@app.get("/api/scanner")
def scanner():
    interval = request.args.get("interval", "5m")
    if interval not in INTERVALS:
        return jsonify({"error": "Invalid interval"}), 400
    started = time.time()
    index_candles = provider.get_many_candles(INDICES, interval, 7)
    stock_candles = provider.get_many_candles(NIFTY_50, interval, 7)
    index_results, stock_results, new_signals = [], [], []

    for symbols, source, target in [(INDICES, index_candles, index_results), (NIFTY_50, stock_candles, stock_results)]:
        for symbol in symbols:
            candles = source.get(symbol, [])
            try:
                result = detect_signal(symbol, interval, candles)
                if isinstance(result, tuple):
                    result, event = result
                    if append_if_new(event):
                        result["new_event"] = event
                        new_signals.append(event)
                target.append(result)
            except Exception as error:
                target.append({
                    "symbol": symbol, "name": DISPLAY_NAMES.get(symbol, symbol), "interval": interval,
                    "category": "index" if symbol in INDICES else "stock",
                    "index_membership": membership(symbol), "index_tags": index_tags(symbol),
                    "candles": annotate_candles(candles), "signal": None, "direction": None, "pattern": None,
                    "new_event": None, "error": str(error),
                })

    sync_csv(read_events(5000))
    return jsonify({
        "success": True, "interval": interval, "checked": len(INDICES) + len(NIFTY_50),
        "index_count": len(INDICES), "stock_count": len(NIFTY_50),
        "elapsed_seconds": round(time.time() - started, 2),
        "server_time": datetime.now(IST).isoformat(),
        "indices": index_results, "stocks": stock_results, "results": index_results + stock_results,
        "new_signals": [enrich_event(e) for e in new_signals],
        "sc_wick_limit_percent": get_sc_limit_percent(),
        "signals": update_dashboard_hold(interval, new_signals),
        "dashboard_hold_seconds": DASHBOARD_HOLD_SECONDS,
    })



@app.get("/api/strategy")
def api_strategy():
    interval = request.args.get("interval", "5m")
    if interval not in INTERVALS:
        return jsonify({"error": "Invalid interval"}), 400
    try:
        validity = max(1, min(int(request.args.get("validity", "5")), 50))
    except ValueError:
        validity = 5
    raw_symbols = request.args.get("symbols", "")
    if raw_symbols.strip():
        selected = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        selected = [s for s in selected if s in NIFTY_50 or s in INDICES]
    else:
        selected = []
    if not selected:
        return jsonify({
            "success": True, "interval": interval, "validity_candles": validity,
            "sc_wick_limit_percent": get_sc_limit_percent(),
            "selected_symbols": [], "selected_count": 0,
            "feed_source": "current scanner market feed (completed OHLC candles)",
            "elapsed_seconds": 0, "server_time": datetime.now(IST).isoformat(),
            "setups": [], "trades": [], "stats": strategy_stats([]),
            "message": "Select at least one instrument before running the strategy."
        })
    backtest_date = request.args.get("backtest_date") or datetime.now(IST).strftime("%Y-%m-%d")
    try:
        datetime.strptime(backtest_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"success": False, "error": "Invalid backtest date. Use YYYY-MM-DD."}), 400
    started = time.time()
    feed = provider.get_many_candles_for_date(selected, interval, backtest_date)
    all_selected_trades = []
    all_setups = []
    data_counts = {s: len(feed.get(s, [])) for s in selected}
    for symbol in selected:
        try:
            request_limit = float(request.args.get("sc_limit")) if request.args.get("sc_limit") is not None else get_sc_limit_percent()
        except (TypeError, ValueError):
            request_limit = get_sc_limit_percent()
        request_limit = max(1.0, request_limit)
        result = evaluate_strategy(symbol, interval, feed.get(symbol, []), validity_candles=validity, selected=True, sc_limit_percent=request_limit, backtest_date=backtest_date)
        for t in result.get("trades", []):
            all_selected_trades.append(enrich_strategy_trade(t))
        for setup in result.get("setups", []):
            all_setups.append(enrich_strategy_setup(setup))
    all_selected_trades.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    all_setups.sort(key=lambda x: x.get("pattern_end_time", ""), reverse=True)
    return jsonify({
        "success": True, "interval": interval, "validity_candles": validity,
        "backtest_date": backtest_date,
        "data_counts": data_counts,
        "sc_wick_limit_percent": get_sc_limit_percent(),
        "selected_symbols": selected, "selected_count": len(selected),
        "feed_source": "current scanner market feed (completed OHLC candles)",
        "elapsed_seconds": round(time.time() - started, 2),
        "server_time": datetime.now(IST).isoformat(),
        "setups": all_setups[:500], "trades": all_selected_trades[:500],
        "stats": strategy_stats(all_selected_trades),
    })


@app.get("/strategy/monthly-study")
def strategy_monthly_study():
    """Separate 30-day date-wise SL/Target study page."""
    return render_template(
        "monthly_strategy.html",
        symbols=NIFTY_50,
        indices=INDICES,
        nifty50=sorted(NIFTY50_STOCKS),
        nifty100=sorted(NIFTY50_STOCKS | NIFTY100_ONLY_STOCKS),
    )

@app.get("/api/strategy/monthly-study")
def api_strategy_monthly_study():
    interval = request.args.get("interval", "5m")
    if interval not in INTERVALS:
        return jsonify({"success": False, "error": "Invalid interval"}), 400

    backtest_date = request.args.get("backtest_date") or datetime.now(IST).strftime("%Y-%m-%d")
    try:
        end_day = datetime.strptime(backtest_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "error": "Invalid backtest date. Use YYYY-MM-DD."}), 400

    raw_symbols = request.args.get("symbols", "")
    selected = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
    selected = list(dict.fromkeys(s for s in selected if s in NIFTY_50 or s in INDICES))
    if not selected:
        return jsonify({"success": False, "error": "Select at least one instrument on the Strategy page before opening the study."}), 400

    side = request.args.get("side", "BOTH").upper()
    if side not in {"BOTH", "LONG", "SHORT"}:
        side = "BOTH"
    try:
        sc_limit = float(request.args.get("sc_limit", get_sc_limit_percent()))
    except (TypeError, ValueError):
        sc_limit = get_sc_limit_percent()
    sc_limit = max(0.01, sc_limit)

    started = time.time()
    rows = []
    total_target = total_sl = total_normal_sl = total_systematic_sl = total_ambiguous = total_trades = total_active = 0
    data_days = 0

    # 30 calendar dates ending on the selected Backtest Date, inclusive.
    for offset in range(29, -1, -1):
        day = end_day - timedelta(days=offset)
        day_text = day.isoformat()
        feed = provider.get_many_candles_for_date(selected, interval, day_text)
        day_trades = []
        candle_count = 0
        instruments_with_data = 0
        for symbol in selected:
            candles = feed.get(symbol, [])
            candle_count += len(candles)
            if candles:
                instruments_with_data += 1
            result = evaluate_strategy(
                symbol, interval, candles, validity_candles=1, selected=True,
                sc_limit_percent=sc_limit, backtest_date=day_text,
            )
            for trade in result.get("trades", []):
                if side != "BOTH" and trade.get("direction") != side:
                    continue
                day_trades.append(trade)

        target_hits = sum(1 for t in day_trades if t.get("result") == "TARGET_HIT")
        sl_hits = sum(1 for t in day_trades if t.get("result") == "SL_HIT")
        systematic_sl = sum(1 for t in day_trades if t.get("result") == "SYSTEMATIC_SL")
        ambiguous = sum(1 for t in day_trades if t.get("result") == "AMBIGUOUS_BOTH_HIT")
        active = sum(1 for t in day_trades if t.get("status") == "ACTIVE" and not t.get("result"))
        normal_sl = sl_hits
        trades_count = len(day_trades)
        has_data = instruments_with_data > 0
        if has_data:
            data_days += 1
        total_target += target_hits
        total_sl += sl_hits + systematic_sl
        total_normal_sl += normal_sl
        total_systematic_sl += systematic_sl
        total_ambiguous += ambiguous
        total_trades += trades_count
        total_active += active
        rows.append({
            "date": day_text,
            "date_display": day.strftime("%d-%m-%Y"),
            "status": "DATA" if has_data else "NO DATA",
            "has_data": has_data,
            "instruments_with_data": instruments_with_data,
            "candle_count": candle_count,
            "trades": trades_count,
            "target_hits": target_hits,
            "sl_hits": sl_hits + systematic_sl,
            "normal_sl_hits": normal_sl,
            "systematic_sl_hits": systematic_sl,
            "ambiguous": ambiguous,
            "active": active,
        })

    resolved = total_target + total_sl
    win_rate = (total_target / resolved * 100.0) if resolved else None
    return jsonify({
        "success": True,
        "backtest_date": backtest_date,
        "period_start": (end_day - timedelta(days=29)).isoformat(),
        "period_end": backtest_date,
        "interval": interval,
        "direction": side,
        "sc_limit_percent": sc_limit,
        "selected_symbols": selected,
        "selected_count": len(selected),
        "rows": rows,
        "totals": {
            "target": total_target,
            "sl": total_sl,
            "normal_sl": total_normal_sl,
            "systematic_sl": total_systematic_sl,
            "ambiguous": total_ambiguous,
            "trades": total_trades,
            "active": total_active,
            "resolved": resolved,
            "win_rate": win_rate,
        },
        "data_days": data_days,
        "elapsed_seconds": round(time.time() - started, 2),
        "data_source": "Stored selected-timeframe OHLC; exact-date online fallback only when local data is missing; no timeframe resampling.",
    })

@app.get("/api/strategy/trades")
def api_strategy_trades():
    try:
        limit = max(1, min(int(request.args.get("limit", "500")), 10000))
    except ValueError:
        limit = 500
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    all_dates = request.args.get("all_dates") == "1"
    # A blank date range means TODAY by default. The UI must explicitly request
    # all archived dates with all_dates=1. This prevents old trades from appearing
    # when the Strategy Lab is opened or refreshed.
    if not all_dates and not date_from and not date_to:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        date_from = today
        date_to = today
    rows = [enrich_strategy_trade(t) for t in strategy_trades(limit, date_from, date_to)]
    return jsonify({
        "success": True, "trades": rows,
        "date_from": date_from, "date_to": date_to, "all_dates": all_dates,
        "storage": strategy_storage_root(),
        "available_dates": strategy_dates(),
        "refreshed_at": datetime.now(IST).isoformat()
    })

@app.post("/api/strategy/clear")
def api_strategy_clear():
    clear_strategy_trades()
    return jsonify({"success": True})


def enrich_strategy_setup(setup):
    x = dict(setup)
    x["category"] = "index" if x.get("symbol") in INDICES else "stock"
    x["index_membership"] = membership(x.get("symbol", ""))
    x["index_tags"] = index_tags(x.get("symbol", ""))
    x["pattern_code"] = "G3R1" if x.get("direction") == "LONG" else "R3G1"
    x["pattern_end_time_display"] = _display_ist(x.get("pattern_end_time"))
    x["sc_wick_limit_percent"] = float(x.get("sc_wick_limit_percent") or get_sc_limit_percent())
    x["sc_strength"] = x.get("sc_strength") or []
    return x

def _display_ist(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        dt = dt.astimezone(IST)
        return dt.strftime("%d-%m-%Y %I:%M:%S %p")
    except Exception:
        return str(value).replace("T", " ").replace("+05:30", "")

def enrich_strategy_trade(trade):
    x = dict(trade)
    x["category"] = "index" if x.get("symbol") in INDICES else "stock"
    x["index_membership"] = membership(x.get("symbol", ""))
    x["index_tags"] = index_tags(x.get("symbol", ""))
    x["pattern_code"] = "G3R1" if x.get("direction") == "LONG" else "R3G1"
    x["created_at_display"] = _display_ist(x.get("created_at"))
    x["updated_at_display"] = _display_ist(x.get("updated_at"))
    x["trigger_time_display"] = x.get("trigger_time_display") or _display_ist(x.get("trigger_time"))
    x["sl_activation_display"] = _display_ist(x.get("sl_activation"))
    x["exit_time_display"] = _display_ist(x.get("exit_time"))
    return x

def strategy_stats(trades):
    total = len(trades)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    target = sum(t.get("result") == "TARGET_HIT" for t in trades)
    sl = sum(t.get("result") == "SL_HIT" for t in trades)
    systematic = sum(t.get("result") == "SYSTEMATIC_SL" for t in trades)
    ambiguous = sum(t.get("result") == "AMBIGUOUS_BOTH_HIT" for t in trades)
    active = sum(t.get("status") == "ACTIVE" for t in trades)
    punched = sum(t.get("status") in ("PUNCHED", "ACTIVE", "CLOSED") for t in trades)
    resolved = target + sl + systematic
    r_values = [float(t["r_multiple"]) for t in trades if isinstance(t.get("r_multiple"), (int, float))]
    return {"setups": total, "trades_punched": punched, "active": active, "closed": len(closed), "target_hits": target, "sl_hits": sl, "systematic_sl": systematic, "ambiguous": ambiguous, "resolved": resolved, "win_rate": round(target / resolved * 100, 2) if resolved else None, "total_r": round(sum(r_values), 2) if r_values else 0}

@app.get("/api/history")
def api_history():
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    raw = read_events(max(1, min(limit, 10000)), date_from, date_to)
    events = [enrich_event(e) for e in raw]
    sync_csv(raw)
    return jsonify({
        "success": True, "events": events,
        "storage": signal_storage_root(),
        "available_dates": signal_dates(),
        "date_from": date_from, "date_to": date_to,
        "sc_wick_limit_percent": get_sc_limit_percent(),
        "refreshed_at": datetime.now(IST).isoformat()
    })

@app.post("/api/history/clear")
def api_history_clear():
    clear_events()
    with dashboard_lock:
        dashboard_signals.clear()
    return jsonify({"success": True})

@app.get("/api/settings")
def api_settings_get():
    return jsonify({"success": True, "settings": get_settings()})

@app.post("/api/settings")
def api_settings_update():
    data = request.get_json(silent=True) or {}
    value = data.get("sc_wick_body_limit_percent")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "SC wick/body limit must be a number"}), 400
    if not __import__("math").isfinite(numeric) or numeric < 1:
        return jsonify({"success": False, "error": "SC wick/body limit must be 1% or higher"}), 400
    settings = update_settings(sc_wick_body_limit_percent=numeric)
    return jsonify({"success": True, "settings": settings, "message": f"SC strength limit updated to {settings['sc_wick_body_limit_percent']:.2f}%"})

if __name__ == "__main__":
    print("FREE NIFTY CANDLE SCANNER v4")
    print("Open: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
