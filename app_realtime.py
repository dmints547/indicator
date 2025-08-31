import os
import time
import threading
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from flask import Flask
from flask_socketio import SocketIO, emit

# --- Config via env vars ---
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "trading")
TABLE = os.getenv("OHLC_TABLE", "ohlc_data")  # time, open, high, low, close, volume
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
INIT_LIMIT = int(os.getenv("INIT_LIMIT", "200"))

engine = create_engine(
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    pool_pre_ping=True,
)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_last_ts = None
_ts_lock = threading.Lock()

def _init_last_ts():
    global _last_ts
    with engine.connect() as conn:
        ts = conn.execute(text(f"SELECT MAX(time) FROM {TABLE}")).scalar()
    with _ts_lock:
        _last_ts = ts

def _fetch_recent(limit=200):
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"""
                SELECT time, open, high, low, close, COALESCE(volume, 0) AS volume
                FROM {TABLE}
                ORDER BY time DESC
                LIMIT :lim
            """),
            conn,
            params={"lim": limit},
        )
    return df.sort_values("time")

def _fetch_new_since(ts):
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"""
                SELECT time, open, high, low, close, COALESCE(volume, 0) AS volume
                FROM {TABLE}
                WHERE time > :ts
                ORDER BY time ASC
            """),
            conn,
            params={"ts": ts},
        )
    return df

def polling_worker():
    global _last_ts
    _init_last_ts()
    while True:
        try:
            with _ts_lock:
                ts = _last_ts
            if ts is None:
                # If table is empty, sleep and retry
                time.sleep(POLL_SECONDS)
                continue
            df = _fetch_new_since(ts)
            for _, row in df.iterrows():
                payload = {
                    "time": row["time"].isoformat() if isinstance(row["time"], datetime) else str(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                with _ts_lock:
                    _last_ts = row["time"]
                socketio.emit("new_candle", payload, namespace="/prices")
        except Exception as e:
            # Log and continue polling
            print(f"[polling_worker] error: {e}")
        time.sleep(POLL_SECONDS)

@socketio.on("connect", namespace="/prices")
def on_connect():
    df = _fetch_recent(INIT_LIMIT)
    candles = [
        {
            "time": (t.isoformat() if isinstance(t, datetime) else str(t)),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v),
        }
        for t, o, h, l, c, v in df[["time", "open", "high", "low", "close", "volume"]].itertuples(index=False, name=None)
    ]
    emit("init_candles", candles)

if __name__ == "__main__":
    threading.Thread(target=polling_worker, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
