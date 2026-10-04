"""In-process publish/subscribe signal bus.

Topics used by Sentinel:
  regime    -> {"ticker": str, "bias": "bullish"|"bearish"|"neutral",
                "confidence": 0..1, "horizon": "swing"|"intraday", "ts": float}
  signal    -> {"strategy": str, "ticker": str, "side": "long"|"short"|"flat",
                "strength": 0..1, "meta": dict}
  risk      -> {"event": "kill"|"resume"|"resize", "scope": "global"|strategy,
                "reason": str}
  fill      -> execution reports from workers
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable


class SignalBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Callable[[dict], None]) -> None:
        with self._lock:
            self._subs[topic].append(handler)

    def publish(self, topic: str, msg: dict) -> None:
        msg = dict(msg)
        msg.setdefault("ts", time.time())
        msg.setdefault("topic", topic)
        with self._lock:
            handlers = list(self._subs.get(topic, []))
        for h in handlers:
            try:
                h(msg)
            except Exception:
                # Bus must never die because one handler failed.
                continue
