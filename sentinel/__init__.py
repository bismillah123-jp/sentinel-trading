"""Sentinel - unified trading orchestration system.

Layers:
  brain      -> TradingAgents (LLM multi-agent, slow loop: regime & bias)
  validation -> backtest gate (no strategy goes live unproven)
  execution  -> Freqtrade (tactical rule-based) + arb_worker (market-neutral)
  risk       -> UnifiedRiskManager (global kill-switch, vol targeting)
"""

__version__ = "0.1.0"
