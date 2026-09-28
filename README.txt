SEPARATE STRATEGY LAB

This is a third, separate Flask page/app. It does NOT modify app.py, history.py, signal_store.py, or the current dashboard.

Place strategy_app.py, templates/strategy.html and static/strategy.css + strategy.js in the SAME ROOT FOLDER as your current project, because strategy_app.py imports the existing data_provider.py. The separate app stores only its own state in data/strategy_trades.jsonl.

Run from the existing project folder:
  .\.venv\Scripts\python.exe strategy_app.py
Open:
  http://127.0.0.1:5001

Strategy:
LONG: G G G R -> breakout above highest high of G1-G3 -> entry at trigger -> SL G3 low -> target RR (default 1:2).
SHORT: R R R G -> breakdown below lowest low of R1-R3 -> entry -> SL R3 high -> target RR (default 1:2).

Important: for live-market safety, same-candle SL+target ambiguity is resolved conservatively as SL first. Default trigger is wick cross. You can switch to candle-close confirmation, add an entry buffer, and set setup expiry.

The feed is the same data_provider.py used by the current project. With the current Yahoo Finance provider, data availability/latency is subject to Yahoo's feed; this page does not create a new broker live feed.
