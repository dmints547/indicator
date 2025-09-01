import pandas as pd
import numpy as np
import pytest

from indicator import compute_indicators

def test_compute_indicators_returns_expected_columns():
    # Create dummy OHLC data
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    df = pd.DataFrame({
        "open": np.random.rand(20) * 100,
        "high": np.random.rand(20) * 100,
        "low": np.random.rand(20) * 100,
        "close": np.random.rand(20) * 100,
        "volume": np.random.randint(100, 1000, size=20)
    }, index=dates)

    result = compute_indicators(df)

    # Basic shape check
    assert not result.empty
    # Example: check that a known indicator column exists
    assert any(col.lower().startswith("sma") for col in result.columns), \
        f"Expected at least one SMA column, got {result.columns.tolist()}"
