# app.py
import numpy as np  # add this
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import requests
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from models import Base, Snapshot
from indicators import compute_indicators
from signals import generate_signal, classify_strength
from streaming.socketio_service import init_socketio

# ---------------- Setup ----------------
load_dotenv()
API_KEY = os.getenv("MARKETSTACK_API_KEY")
if not API_KEY:
    raise RuntimeError("MARKETSTACK_API_KEY is not set in environment or .env")

DEFAULT_SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "AAPL").split(",") if s.strip()]
TIMEFRAMES = ["4hour", "2hour", "1hour", "30min", "15min", "5min", "3min", "1min"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": CORS_ORIGINS}})
socketio = SocketIO(app, cors_allowed_origins=CORS_ORIGINS, async_mode="threading")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("marketstack")

# ---------------- Database ----------------
DB_URL = os.getenv("DATABASE_URL", "sqlite:///market.db")
engine = create_engine(DB_URL, future=True)
Base.metadata.create_all(engine)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))

# ---------------- Cache ----------------
CACHE: Dict[str, List[Dict[str, Any]]] = {}
MAX_CACHE_BARS = 1200  # keep enough for higher TFs

# ---------------- Helpers ----------------
def timeframe_minutes(tf: str) -> int:
    if tf.endswith("min"):
        return int(tf.replace("min", ""))
    if tf.endswith("hour"):
        return int(tf.replace("hour", "")) * 60
    raise ValueError(f"Unsupported timeframe: {tf}")

def pandas_offset(tf: str) -> str:
    return f"{timeframe_minutes(tf)}T"

def marketstack_intraday_api(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Fetch from Marketstack Intraday API for a given interval. Return empty df on failure."""
    url = "https://api.marketstack.com/v1/intraday"
    params = {
        "access_key": API_KEY,
        "symbols": symbol,
        "interval": interval,
        "limit": limit,
        "sort": "ASC",
    }
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data", [])
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df.rename(columns={"date": "ts"}, inplace=True)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            cols = ["ts", "open", "high", "low", "close", "volume"]
            df = df[[c for c in cols if c in df.columns]].copy()
            df.sort_values("ts", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning(f"[{symbol} {interval}] API error: {e} (retry {attempt+1}/4 in {wait}s)")
            time.sleep(wait)
    return pd.DataFrame()

def resample_ohlcv(df_1m: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample 1-minute OHLCV to target timeframe."""
    if df_1m.empty:
        return df_1m
    df = df_1m.copy()
    df.set_index("ts", inplace=True)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df.resample(pandas_offset(tf)).agg(agg).dropna().reset_index()
    return out

def marketstack_intraday(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """
    Try to fetch the exact interval. If empty (unsupported tier or interval),
    fall back to 1min and resample.
    """
    df = marketstack_intraday_api(symbol, interval, limit)
    if not df.empty:
        return df

    # Fallback: derive from 1min
    factor = max(1, timeframe_minutes(interval))
    # Pull enough 1min bars to produce 'limit' bars at the target TF
    base_limit = min(5000, limit * factor)  # cap to be safe
    df1 = marketstack_intraday_api(symbol, "1min", base_limit)
    if df1.empty:
        return df1
    out = resample_ohlcv(df1, interval)
    return out.tail(limit)

def cache_key(symbol: str, tf: str) -> str:
    return f"{symbol}_{tf}"

def upsert_cache(key: str, df: pd.DataFrame):
    if df.empty:
        return
    arr = CACHE.setdefault(key, [])
    for _, r in df.iterrows():
        bar = {
            "ts": r["ts"].isoformat() if isinstance(r["ts"], pd.Timestamp) else pd.to_datetime(r["ts"], utc=True).isoformat(),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume") or 0.0),
        }
        if not arr or arr[-1]["ts"] != bar["ts"]:
            arr.append(bar)
            if len(arr) > MAX_CACHE_BARS:
                del arr[0 : len(arr) - MAX_CACHE_BARS]

def persist_snapshots(symbol: str, tf: str, df: pd.DataFrame):
    if df.empty:
        return
    session = SessionLocal()
    try:
        for _, r in df.iterrows():
            ts = r["ts"].to_pydatetime() if isinstance(r["ts"], pd.Timestamp) else pd.to_datetime(r["ts"], utc=True).to_pydatetime()
            exists = (
                session.query(Snapshot)
                .filter(Snapshot.symbol == symbol, Snapshot.timeframe == tf, Snapshot.ts == ts)
                .first()
            )
            if exists:
                continue
            snap = Snapshot(
                symbol=symbol,
                timeframe=tf,
                ts=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume") or 0.0),
            )
            session.add(snap)
        session.commit()
    finally:
        session.close()

def compute_and_emit(symbol: str, tf: str):
    key = cache_key(symbol, tf)
    bars = CACHE.get(key, [])
    # Need enough bars for indicators (e.g., 50+)
    if len(bars) < 60:
        return
    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    df_ind = compute_indicators(df)
    sig = generate_signal(df_ind)

    strength = classify_strength(sig["trend"], sig["confidence"])
    payload = {
        "symbol": symbol,
        "timeframe": tf,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trend": sig["trend"],
        "strength": strength,
        "entry": sig["entry"],
        "stop_loss": sig["stop_loss"],
        "take_profit": sig["take_profit"],
        "confidence": sig["confidence"],
        "explain": sig["explain"],
        "last_close": float(df_ind["close"].iloc[-1]),
    }
    socketio.emit("signal", payload, namespace="/ws", broadcast=True)
    log.info(f"[{symbol} {tf}] {strength} ({sig['trend']}) conf={sig['confidence']:.2f}")

def poll_symbols():
    for symbol in DEFAULT_SYMBOLS:
        for tf in TIMEFRAMES:
            # Use larger limit for high TF to stabilize indicators
            base_limit = 400 if tf.endswith("hour") else 300
            df = marketstack_intraday(symbol, interval=tf, limit=base_limit)
            if df.empty:
                continue
            upsert_cache(cache_key(symbol, tf), df)
            persist_snapshots(symbol, tf, df)
            compute_and_emit(symbol, tf)
            
def safe_float(x):
    try:
        if x is None:
            return None
        xf = float(x)
        return xf if np.isfinite(xf) else None
    except Exception:
        return None

def build_indicators_payload(df_ind: pd.DataFrame, limit: int = 150, fields: Optional[List[str]] = None):
    default_fields = [
        "close","sma20","sma50","ema12","ema26","rsi14",
        "macd","macd_signal","macd_hist","bb_ma","bb_up","bb_lo","atr14"
    ]
    cols = fields or default_fields
    # Keep only existing columns
    cols = [c for c in cols if c in df_ind.columns]
    slim = df_ind[cols].tail(limit).copy()
    idx = slim.index.to_pydatetime()
    out = {
        "ts": [t.replace(tzinfo=timezone.utc).isoformat() for t in idx]
    }
    for c in cols:
        out[c] = [safe_float(v) for v in slim[c].tolist()]
    return out

# ---------------- Scheduler ----------------
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(poll_symbols, "interval", seconds=POLL_SECONDS, id="poll_job")
scheduler.start()

# ---------------- REST APIs ----------------
@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat(), "symbols": DEFAULT_SYMBOLS, "timeframes": TIMEFRAMES})

@app.get("/api/timeframes")
def list_timeframes():
    return jsonify({"timeframes": TIMEFRAMES})

@app.get("/api/snapshots")
def snapshots():
    symbol = request.args.get("symbol", DEFAULT_SYMBOLS[0]).upper()
    tf = request.args.get("tf", TIMEFRAMES[-1])  # default last = 1min
    limit = int(request.args.get("limit", "200"))
    key = cache_key(symbol, tf)
    bars = CACHE.get(key, [])[-limit:]
    if bars:
        return jsonify({"symbol": symbol, "timeframe": tf, "bars": bars})
    # Fallback: DB
    session = SessionLocal()
    try:
        q = (
            session.query(Snapshot)
            .filter(Snapshot.symbol == symbol, Snapshot.timeframe == tf)
            .order_by(Snapshot.ts.desc())
            .limit(limit)
            .all()
        )
        out = [
            {
                "ts": s.ts.replace(tzinfo=timezone.utc).isoformat(),
                "open": s.open,
                "high": s.high,
                "low": s.low,
                "close": s.close,
                "volume": s.volume,
            }
            for s in reversed(q)
        ]
        return jsonify({"symbol": symbol, "timeframe": tf, "bars": out})
    finally:
        session.close()

@app.get("/api/signal")
def api_signal():
    symbol = request.args.get("symbol", DEFAULT_SYMBOLS[0]).upper()
    tf = request.args.get("tf", TIMEFRAMES[-1])  # default 1min
    key = cache_key(symbol, tf)
    bars = CACHE.get(key, [])
    if len(bars) < 60:
        return jsonify({"error": "insufficient data"}), 425
    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)
    df_ind = compute_indicators(df)
    sig = generate_signal(df_ind)
    strength = classify_strength(sig["trend"], sig["confidence"])
    return jsonify(
        {
            "symbol": symbol,
            "timeframe": tf,
            "trend": sig["trend"],
            "strength": strength,
            "entry": sig["entry"],
            "stop_loss": sig["stop_loss"],
            "take_profit": sig["take_profit"],
            "confidence": sig["confidence"],
            "explain": sig["explain"],
            "last_close": float(df_ind["close"].iloc[-1]),
            "time": datetime.now(timezone.utc).isoformat(),
        }
    )

# ---------------- WebSocket ----------------
@socketio.on("connect", namespace="/ws")
def ws_connect():
    emit("welcome", {"msg": "connected to signal stream"})

if __name__ == "__main__":
    # Prime cache on boot
    poll_symbols()
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)

# ---------------- diagnostics ----------------
@app.get("/api/diagnostics")
def diagnostics():
    symbol = request.args.get("symbol", DEFAULT_SYMBOLS[0]).upper()
    tf = request.args.get("tf", TIMEFRAMES[-1])  # default 1min
    limit = int(request.args.get("limit", "150"))
    # Optional: comma-separated list of indicator fields
    fields_param = request.args.get("fields")
    field_list = [f.strip() for f in fields_param.split(",")] if fields_param else None

    key = cache_key(symbol, tf)
    bars = CACHE.get(key, [])
    if len(bars) < 60:
        return jsonify({"error": "insufficient data"}), 425

    df = pd.DataFrame(bars)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.set_index("ts", inplace=True)

    df_ind = compute_indicators(df)
    sig = generate_signal(df_ind)
    strength = classify_strength(sig["trend"], sig["confidence"])

    indicators = build_indicators_payload(df_ind, limit=limit, fields=field_list)

    # Latest indicator snapshot (single row)
    latest = df_ind.iloc[-1]
    latest_snapshot = {
        "close": safe_float(latest.get("close")),
        "sma20": safe_float(latest.get("sma20")),
        "sma50": safe_float(latest.get("sma50")),
        "ema12": safe_float(latest.get("ema12")),
        "ema26": safe_float(latest.get("ema26")),
        "rsi14": safe_float(latest.get("rsi14")),
        "macd": safe_float(latest.get("macd")),
        "macd_signal": safe_float(latest.get("macd_signal")),
        "macd_hist": safe_float(latest.get("macd_hist")),
        "bb_ma": safe_float(latest.get("bb_ma")),
        "bb_up": safe_float(latest.get("bb_up")),
        "bb_lo": safe_float(latest.get("bb_lo")),
        "atr14": safe_float(latest.get("atr14")),
    }

    return jsonify({
        "meta": {
            "symbol": symbol,
            "timeframe": tf,
            "count": len(indicators.get("ts", [])),
            "note": "Initial values may be null until rolling windows warm up."
        },
        "latest_signal": {
            "trend": sig["trend"],
            "strength": strength,
            "confidence": safe_float(sig["confidence"]),
            "entry": safe_float(sig["entry"]),
            "stop_loss": safe_float(sig["stop_loss"]),
            "take_profit": safe_float(sig["take_profit"]),
            "last_close": safe_float(latest_snapshot["close"]),
            "explain": sig["explain"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "latest_indicators": latest_snapshot,
        "series": indicators
    })

