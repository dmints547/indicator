# indicators.py
import pandas as pd
import numpy as np

def SMA(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()

def EMA(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def RSI(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    roll_up = gains.rolling(period).mean()
    roll_down = losses.rolling(period).mean().replace(0, np.nan)
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.bfill()

def MACD(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = EMA(series, fast)
    ema_slow = EMA(series, slow)
    macd = ema_fast - ema_slow
    signal_line = EMA(macd, signal)
    hist = macd - signal_line
    return macd, signal_line, hist

def Bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0):
    ma = SMA(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return ma, upper, lower

def ATR(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = SMA(out["close"], 20)
    out["sma50"] = SMA(out["close"], 50)
    out["ema12"] = EMA(out["close"], 12)
    out["ema26"] = EMA(out["close"], 26)
    out["rsi14"] = RSI(out["close"], 14)
    macd, sig, hist = MACD(out["close"])
    out["macd"] = macd
    out["macd_signal"] = sig
    out["macd_hist"] = hist
    bb_ma, bb_up, bb_lo = Bollinger(out["close"], 20, 2.0)
    out["bb_ma"] = bb_ma
    out["bb_up"] = bb_up
    out["bb_lo"] = bb_lo
    out["atr14"] = ATR(out["high"], out["low"], out["close"], 14)
    return out
