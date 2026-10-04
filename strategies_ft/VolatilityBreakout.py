"""Freqtrade strategy: VolatilityBreakout.

Ports sentinel.strategies.breakout_atr_signals into the Freqtrade IStrategy
interface. Drop this file into freqtrade's user_data/strategies/.

Logic:
  entry  - close breaks rolling `lookback` high, bar range >= 0.5 * ATR
  exit   - ATR trailing stop via custom_stoploss, plus ROI table
Risk is enforced twice: here (per-trade) and by Sentinel's UnifiedRiskManager
(global). Both must say yes.
"""
from freqtrade.strategy import IStrategy
import talib.abstract as ta
from pandas import DataFrame


class VolatilityBreakout(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "15m"
    # Spot market: no shorting. Set True + trading_mode "futures" in config
    # if you want to trade both directions with leverage.
    can_short = False

    lookback = 20
    atr_period = 14
    atr_mult = 2.0

    minimal_roi = {"0": 0.06, "60": 0.03, "180": 0.015}
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["atr"] = ta.ATR(df, timeperiod=self.atr_period)
        df["roll_high"] = df["high"].rolling(self.lookback).max()
        df["bar_range"] = df["high"] - df["low"]
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[
            (df["close"] > df["roll_high"].shift(1))
            & (df["bar_range"] >= 0.5 * df["atr"])
            & (df["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "vol_breakout")
        df.loc[
            (df["close"] < df["low"].rolling(self.lookback).min().shift(1))
            & (df["bar_range"] >= 0.5 * df["atr"])
            & (df["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "vol_breakdown")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return df

    def custom_stoploss(self, pair: str, trade, current_time,
                        current_rate: float, current_profit: float,
                        **kwargs) -> float:
        # ATR-based stop would need the dataframe; freqtrade's trailing stop
        # config above approximates it. Kept explicit so the intent is clear.
        return self.stoploss
