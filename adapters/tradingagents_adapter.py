"""Brain adapter - plugs San's TradingAgents homelab into the Sentinel bus.

It runs the existing `ta.sh` (slow loop: 5-15 min per ticker), parses the
final decision, and translates it into a `regime` message:
  {"ticker", "bias": bullish|bearish|neutral|uncertain, "confidence",
   "volatility": high|low, "horizon": "swing"}

Set SENTINEL_TA_DIR to the tradingagents checkout (default: ~/tradingagents).
Nothing in the upstream repo is modified; this only shells out to it.
"""
from __future__ import annotations

import os
import re
import subprocess

BULLISH = re.compile(r"\b(buy|overweight|bullish|long|strong buy)\b", re.I)
BEARISH = re.compile(r"\b(sell|underweight|bearish|short|strong sell)\b", re.I)
HIGH_VOL = re.compile(r"\b(volatile|high volatility|whipsaw|cascade)\b", re.I)


def analyze(ticker: str, date: str | None = None,
            rounds: int = 1, timeout: int = 1200) -> dict:
    ta_dir = os.environ.get("SENTINEL_TA_DIR",
                            os.path.expanduser("~/tradingagents"))
    cmd = [os.path.join(ta_dir, "ta.sh"), ticker]
    if date:
        cmd.append(date)
    cmd.append(str(rounds))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=ta_dir)
    out = proc.stdout + proc.stderr
    decision = out.split("=== KEPUTUSAN ===")[-1].strip() if "=== KEPUTUSAN ===" in out else out[-2000:]

    bias = "uncertain"
    if BULLISH.search(decision):
        bias = "bullish"
    elif BEARISH.search(decision):
        bias = "bearish"
    elif re.search(r"\b(hold|neutral|wait)\b", decision, re.I):
        bias = "neutral"

    # Confidence heuristic: explicit numbers > hedged language.
    confidence = 0.5
    m = re.search(r"confidence[:\s]+(\d{1,3})", decision, re.I)
    if m:
        confidence = min(0.95, int(m.group(1)) / 100)
    elif re.search(r"\b(however|on the other hand|mixed|uncertain)\b", decision, re.I):
        confidence = 0.35

    return {"ticker": ticker, "bias": bias, "confidence": confidence,
            "volatility": "high" if HIGH_VOL.search(decision) else "low",
            "horizon": "swing", "raw": decision[:500]}
