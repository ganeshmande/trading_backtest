import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_PATH = os.path.join(DATA_DIR, "strategy_settings.json")
_LOCK = threading.Lock()
DEFAULTS = {"sc_wick_body_limit_percent": 40.0}


def _sanitize(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return DEFAULTS["sc_wick_body_limit_percent"]
    return max(1.0, round(value, 2))


def get_settings():
    os.makedirs(DATA_DIR, exist_ok=True)
    with _LOCK:
        data = dict(DEFAULTS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
        data["sc_wick_body_limit_percent"] = _sanitize(data.get("sc_wick_body_limit_percent"))
        return data


def get_sc_limit_percent():
    return get_settings()["sc_wick_body_limit_percent"]


def update_settings(sc_wick_body_limit_percent=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    with _LOCK:
        current = dict(DEFAULTS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    current.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
        if sc_wick_body_limit_percent is not None:
            current["sc_wick_body_limit_percent"] = _sanitize(sc_wick_body_limit_percent)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
        return current
