# Sentinel — Unified Trading Orchestration

Satu sistem yang mengorkestrasi 6 komponen jadi satu alur kerja.
Bukan "dilebur jadi satu file" (itu tidak mungkin secara jujur: beda bahasa,
beda arsitektur, beda lisensi) — tapi **satu otak orkestrasi** di mana tiap
komponen mengerjakan yang dia paling jago.

```
                    ┌─────────────────────────┐
                    │   TradingAgents (brain) │  6. zip homelab (analisa LLM, slow loop)
                    │  regime + bias / ticker │
                    └────────────┬────────────┘
                                 │ regime msg
                    ┌────────────▼────────────┐
                    │      ORCHESTRATOR       │
                    │  regime -> strategy     │──┐
                    └────────────┬────────────┘  │
                        passport │               │ risk events
                    ┌────────────▼────────────┐  │
                    │   VALIDATION GATE (5)   │  │
                    │  Jesse-style: no proof, │  │
                    │  no live trading        │  │
                    └────────────┬────────────┘  │
               ┌─────────────────┼─────────────────┐
               │                 │                 │
   ┌───────────▼──────┐  ┌──────▼───────┐  ┌──────▼────────┐
   │ 1. FREQTRADE     │  │ 2/6. ARB     │  │ RISK MANAGER  │
   │ tactical exec    │  │ market-neutral│  │ (global)      │
   │ breakout/grid    │  │ Hummingbot-   │  │ kill-switch,  │
   │ spot & futures   │  │ style + bar-  │  │ vol targeting │
   └──────────────────┘  │ botine logic  │  └───────────────┘
                         └───────────────┘
   3. NautilusTrader = upgrade path mesin eksekusi (Rust core)
   4. TradingAgents  = brain (di atas)
```

## Pemetaan 6 komponen

| # | Komponen | Peran di Sentinel | Status |
|---|----------|-------------------|--------|
| 1 | Freqtrade | Eksekutor taktis (breakout/grid, spot+futures) | Adapter REST siap (`adapters/freqtrade_adapter.py`), strategi di `strategies_ft/` |
| 2 | Hummingbot | Market-making/arb profesional | Pola strateginya dipakai di `workers/arb_worker.py`; full node = upgrade path |
| 3 | NautilusTrader | Mesin kelas institusi | Upgrade path (ganti core eksekusi saat butuh performa Rust) |
| 4 | TradingAgents | Brain: analisa regime & bias (slow loop) | Adapter siap (`adapters/tradingagents_adapter.py` -> `ta.sh` homelab) |
| 5 | Jesse | Filosofi validasi: backtest tanpa look-ahead | Diwujudkan sebagai `sentinel/validation.py` (BacktestGate) |
| 6 | barbotine + zip homelab | Ide arb tanpa transfer + setup lokal | Ditingkatkan di `workers/arb_worker.py` (liquidity filter, skew rebalance) |

## Cara kerja (urutan wajib)

1. **Brain** menganalisa tiap ticker (lambat, mendalam) -> kirim `regime`.
2. **Orchestrator** memetakan regime -> profil strategi (bullish+vol tinggi = breakout,
   sideways = grid, uncertain = arb saja).
3. **Validation gate** memeriksa paspor backtest strategi itu. Tidak lolos -> fallback
   ke arb/flat. Tidak ada strategi yang live tanpa bukti.
4. **Worker** mengeksekusi. Setiap order lewat **RiskManager** dulu: kill-switch
   harian (-3%), kunci profit (+2%), position sizing berbasis ATR.

## Yang JUJUR harus dipahami

- Menumpuk 6 framework **tidak mengalikan win rate**. Yang bikin "akurat" adalah:
  strategi yang lolos backtest jujur + sizing adaptif + berani mematikan yang rugi.
- Sistem ini mengurangi *operational risk* dan menambah lapisan konfirmasi —
  bukan mesin cetak uang.
- Urutan deployment yang benar: **backtest -> dry-run -> modal kecil -> scale up**.
- Lisensi: Freqtrade GPL-3.0. Jangan distribusikan gabungan ini sebagai produk
  closed-source. Pakai privat = aman.

## Quickstart

```bash
cd sentinel
python3 tests/test_sentinel.py          # smoke test (harus ALL PASSED)

# 1. Brain (di homelab, sudah ada):
SENTINEL_TA_DIR=~/tradingagents python3 -c "
from adapters.tradingagents_adapter import analyze
print(analyze('BTC-USD'))"

# 2. Freqtrade (install terpisah, official docs):
#    - copy strategies_ft/VolatilityBreakout.py ke user_data/strategies/
#    - aktifkan api_server di config, lalu:
SENTINEL_FT_URL=http://127.0.0.1:8080 SENTINEL_FT_USER=... SENTINEL_FT_PASS=... \
python3 -c "
from adapters.freqtrade_adapter import FreqtradeClient
c = FreqtradeClient(); print(c.profit())"

# 3. Full stack:
docker compose up -d
```

## Struktur

```
sentinel/sentinel/     core: bus, risk, orchestrator, validation, strategies
sentinel/adapters/     jembatan ke TradingAgents & Freqtrade
sentinel/workers/      arb_worker (market-neutral)
sentinel/strategies_ft/ strategi Freqtrade siap deploy
sentinel/tests/        smoke test
```
