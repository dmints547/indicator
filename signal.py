# signals.py
from typing import Dict, Any
import numpy as np
import pandas as pd

def _normalize(value, lo, hi):
    if not np.isfinite(hi) or not np.isfinite(lo) or hi == lo:
        return 0.5
    return float((value - lo) / (hi - lo))

def generate_signal(df: pd.DataFrame) -> Dict[str, Any]:
    row = df.iloc[-1]
    trend_up = row["ema12"] > row["ema26"]
    rsi = float(row["rsi14"])
    macd_hist = float(row["macd_hist"]) if np.isfinite(row["macd_hist"]) else 0.0
    price = float(row["close"])
    atr = float(row["atr14"]) if np.isfinite(row["atr14"]) else 0.0
    bb_up = float(row["bb_up"]) if np.isfinite(row["bb_up"]) else np.nan
    bb_lo = float(row["bb_lo"]) if np.isfinite(row["bb_lo"]) else np.nan

    s_trend = 1.0 if trend_up else 0.0
    s_rsi = 1.0 if 50 < rsi < 70 else (0.5 if 30 <= rsi <= 50 else 0.0)
    s_macd = 1.0 if macd_hist > 0 else 0.0
    price_loc = _normalize(price, bb_lo, bb_up)
    s_boll = 1.0 - abs(0.5 - price_loc) * 2  # favor mid-band

    weights = {"trend": 0.35, "rsi": 0.2, "macd": 0.25, "boll": 0.2}
    confidence = (
        weights["trend"] * s_trend
        + weights["rsi"] * s_rsi
        + weights["macd"] * s_macd
        + weights["boll"] * s_boll
    )

    if s_trend >= 0.5 and (s_macd >= 0.5 or rsi > 50):
        trend = "Bullish"
    elif not s_trend and (s_macd < 0.5 or rsi < 50):
        trend = "Bearish"
    else:
        trend = "Sideways"

    entry = float(price)
    stop_loss = entry - 1.5 * atr if trend == "Bullish" else entry + 1.5 * atr
    take_profit = entry + 3.0 * atr if trend == "Bullish" else entry - 3.0 * atr

    explain = {
        "trend_up": bool(trend_up),
        "rsi": rsi,
        "macd_hist": macd_hist,
        "price_loc_bb": float(price_loc),
        "atr": atr,
    }

    return {
        "trend": trend,
        "entry": entry,
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "confidence": float(confidence),
        "explain": explain,
    }

def classify_strength(trend: str, confidence: float) -> str:
    if confidence >= 0.8:
        return "Strong Buy" if trend == "Bullish" else ("Strong Sell" if trend == "Bearish" else "Neutral")
    if confidence >= 0.6:
        return "Buy" if trend == "Bullish" else ("Sell" if trend == "Bearish" else "Neutral")
    return "Neutral"
