"""Strategy signal library (pure Python, no exchange deps).

These functions compute signals from OHLCV candles and are written so they
can be ported 1:1 into a Freqtrade IStrategy (see strategies_ft/).
Candle format: dicts with keys open/high/low/close/volume.
"""
from __future__ import annotations


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(candles: list[dict], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    if len(candles) < period + 1:
        return out
    trs = [true_range(c["high"], c["low"], candles[i - 1]["close"])
           for i, c in enumerate(candles) if i > 0]
    # Wilder's smoothing
    a = sum(trs[:period]) / period
    out[period] = a
    for i in range(period + 1, len(candles)):
        a = (a * (period - 1) + trs[i - 1]) / period
        out[i] = a
    return out


def rolling_high(candles: list[dict], period: int, i: int) -> float:
    return max(c["high"] for c in candles[max(0, i - period):i])


def breakout_atr_signals(candles: list[dict], lookback: int = 20,
                         atr_period: int = 14,
                         atr_mult: float = 2.0) -> list[dict]:
    """MBT-style volatility breakout.

    Long signal: close breaks above rolling high AND the breakout bar's range
    is meaningful vs ATR (filters chop). Exit handled by ATR trailing stop
    in the executor (freqtrade stoploss / custom_stoploss).
    Returns list of {"index": i, "side": "long"} signals.
    """
    signals: list[dict] = []
    atrs = atr(candles, atr_period)
    for i in range(lookback + 1, len(candles)):
        a = atrs[i]
        if a is None or a <= 0:
            continue
        c = candles[i]
        hi = rolling_high(candles, lookback, i)
        bar_range = c["high"] - c["low"]
        if c["close"] > hi and bar_range >= 0.5 * a:
            signals.append({"index": i, "side": "long",
                            "price": c["close"], "atr": a,
                            "stop": c["close"] - atr_mult * a})
    return signals


def grid_levels(lower: float, upper: float, n: int) -> list[float]:
    """Evenly spaced grid levels for range harvesting (spot)."""
    if n < 2 or upper <= lower:
        return []
    step = (upper - lower) / (n - 1)
    return [lower + i * step for i in range(n)]
