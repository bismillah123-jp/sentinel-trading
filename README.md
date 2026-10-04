# Sentinel — Orkestrasi Trading Otomatis

**Satu sistem yang menggabungkan 6 komponen trading terbaik jadi satu alur kerja:**
Freqtrade · Hummingbot · NautilusTrader · TradingAgents · Jesse · Barbotine.

Bukan dilebur jadi satu file (itu mustahil secara jujur — beda bahasa, beda lisensi),
tapi **satu orkestrasi**: tiap komponen mengerjakan yang dia paling jago,
dijaga satu risk manager global.

```
                    ┌─────────────────────────┐
                    │   TradingAgents (brain) │  analisa LLM multi-agent (slow loop)
                    │  regime + bias / ticker │
                    └────────────┬────────────┘
                                 │ regime msg
                    ┌────────────▼────────────┐
                    │      ORCHESTRATOR       │  pilih strategi sesuai regime
                    └────────────┬────────────┘
                        passport │  (lolos backtest?)
                    ┌────────────▼────────────┐
                    │   VALIDATION GATE       │  filosofi Jesse: no proof, no live
                    └────────────┬────────────┘
               ┌─────────────────┼─────────────────┐
               │                 │                 │
   ┌───────────▼──────┐  ┌──────▼───────┐  ┌──────▼────────┐
   │    FREQTRADE     │  │ ARB WORKER   │  │ RISK MANAGER  │
   │ eksekusi taktis  │  │ market-      │  │ kill-switch,  │
   │ breakout / grid  │  │ neutral      │  │ vol targeting │
   │ spot & futures   │  │ (pola Hum-   │  │ (global)      │
   └──────────────────┘  │ mingbot +    │  └───────────────┘
                         │ barbotine)   │
                         └──────────────┘
   NautilusTrader = upgrade path mesin eksekusi (Rust) saat butuh performa
```

---

## Cara kerja

Alurnya selalu berurutan, tidak bisa dilangkahi:

1. **Brain (TradingAgents)** menganalisa tiap ticker secara mendalam (5–15 menit per
   analisa). Outputnya bukan order, melainkan *regime*: `bullish / bearish / neutral /
   uncertain` + confidence. Lambat tapi dalam — cocok untuk keputusan arah besar.
2. **Orchestrator** memetakan regime ke profil strategi:
   - `bullish/bearish` + volatilitas tinggi → **breakout_atr** (momentum, pola MBT)
   - volatilitas rendah / sideways → **grid** (panen range)
   - `uncertain` → **arb saja** (mode jaga modal, non-direksional)
3. **Validation gate** memeriksa *paspor backtest* strategi itu. Syarat lolos: minimal
   30 trade, profit factor ≥ 1.2, drawdown ≤ 25%, ada uji out-of-sample, fee dihitung,
   bebas look-ahead bias. **Tidak lolos = tidak boleh live**, otomatis fallback ke arb/flat.
4. **Worker** mengeksekusi: Freqtrade untuk strategi direksional, arb_worker untuk
   arbitrase antar-exchange yang market-neutral.
5. **Risk manager** menjaga semuanya: setiap order dicek dulu. Kill-switch global aktif
   kalau rugi harian ≥ 3%; kunci profit kalau +2%; position sizing otomatis mengecil
   saat volatilitas melebar (volatility targeting).

**Kenapa dibagi begini?** Karena tidak ada satu metode yang menang di semua kondisi
market. Yang bikin sistem tahan lama: strategi yang terbukti + sizing adaptif +
berani mematikan yang rugi. Itu yang diorkestrasi di sini.

---

## Instalasi super cepat (disarankan)

Satu script, berurutan, otomatis — dari nol sampai jalan:

```bash
git clone https://github.com/bismillah123-jp/sentinel-trading.git
cd sentinel-trading
./bootstrap.sh
```

Yang dilakukan script, berurutan:
1. Cek prasyarat (Python ≥ 3.11, git, docker)
2. `pip install .` (install perintah `sentinel`)
3. **Test otomatis** — wajib lolos sebelum lanjut
4. Buat `config.yml` dari contoh
5. Deploy strategi ke `~/.freqtrade/user_data`
6. Pull image Freqtrade
7. Generate `config.json` Freqtrade (dry-run, api_server aktif)
8. Download data historis 90 hari (BTC/ETH/SOL, 15m)
9. *(opsional, flag `--backtest`)* Backtest strategi dulu
10. Jalankan Freqtrade dalam mode **dry-run**
11. `sentinel doctor` — cek kesehatan
12. Langsung menjalankan orkestrasi paper-mode

Flag tambahan: `--backtest` (backtest dulu), `--no-run` (setup saja),
`--dry-run` (lihat rencananya tanpa eksekusi), `--yes` (non-interaktif).

---

## Instalasi manual

Kalau mau paham tiap langkahnya:

```bash
# 1. Ambil repo & install
git clone https://github.com/bismillah123-jp/sentinel-trading.git
cd sentinel-trading
pip install .

# 2. Test dulu (wajib hijau semua)
python3 tests/test_sentinel.py
python3 -m sentinel demo      # simulasi end-to-end

# 3. Config
cp config.example.yml config.yml   # sesuaikan ticker & alokasi

# 4. Freqtrade via Docker
docker pull freqtradeorg/freqtrade:stable
mkdir -p ~/.freqtrade/user_data
./scripts/deploy_strategy.sh ~/.freqtrade/user_data
# - isi config.json (lihat contoh di bawah), aktifkan api_server
# - download data, backtest, lalu:
docker run -d --name sentinel-freqtrade -p 8080:8080 \
  -v ~/.freqtrade/user_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable trade \
  --config /freqtrade/user_data/config.json \
  --strategy VolatilityBreakout --dry-run

# 5. Jalan
export SENTINEL_TA_DIR=~/tradingagents          # brain (opsional)
export SENTINEL_FT_URL=http://127.0.0.1:8080 SENTINEL_FT_USER=... SENTINEL_FT_PASS=...
sentinel run --config config.yml
```

Kebutuhan minimum: Python 3.11+, Docker, RAM 2GB. Core Sentinel sendiri
stdlib-only (ringan); yang berat hanya Freqtrade di Docker.

---

## Setup

### Telegram (kontrol dari HP)

Freqtrade punya bot Telegram bawaan. Setup:

1. Chat **@BotFather** → `/newbot` → dapat **token**
2. Chat **@userinfobot** → dapat **chat_id**
3. Masukkan ke `~/.freqtrade/user_data/config.json`:
```json
"telegram": { "enabled": true, "token": "TOKEN_BOTFATHER", "chat_id": "CHAT_ID" }
```
4. Atau saat bootstrap: `TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=... ./bootstrap.sh`

Perintah Telegram yang bisa dipakai: `/profit` (cuan total), `/status` (posisi terbuka),
`/balance`, `/daily` (P/L harian), `/performance` (per pair), `/forceexit` (tutup paksa).

### `config.yml` (orkestrasi)

```yaml
paper_equity: 10000
tickers: [BTC/USDT, ETH/USDT]
brain_interval_sec: 600
risk:
  daily_loss_limit_pct: 3.0     # kill-switch global
  daily_profit_target_pct: 2.0  # kunci profit, stop entry
  max_total_drawdown_pct: 10.0
allocations:                    # % ekuitas per strategi
  breakout_atr: 50.0
  grid: 30.0
  arb: 20.0
```

### Environment variables

| Variable | Untuk | Default |
|---|---|---|
| `SENTINEL_TA_DIR` | lokasi TradingAgents (brain) | `~/tradingagents` |
| `SENTINEL_FT_URL` | URL api_server Freqtrade | `http://127.0.0.1:8080` |
| `SENTINEL_FT_USER` / `SENTINEL_FT_PASS` | login api_server | — |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | notif Telegram (bootstrap) | kosong = nonaktif |

> **Keamanan:** jangan pernah commit file berisi secret (`.env`, `config.json` asli,
> `config.yml` berisi kredensial). `.gitignore` repo ini sudah menolaknya.

### Brain (TradingAgents, opsional)

Kalau sudah punya setup TradingAgents (misal di `~/tradingagents` dengan `ta.sh`),
cukup set `SENTINEL_TA_DIR`. Tanpa itu, orchestrator jalan dalam **mode simulasi**
(regime netral → profil aman). Brain hanya memberi arah; eksekusi tetap lewat
Freqtrade/arb_worker.

---

## Urutan wajib sebelum live (jangan dilangkahi)

```bash
# 1. Download data
docker exec sentinel-freqtrade freqtrade download-data --exchange binance

# 2. Backtest — strategi harus lolos validation gate
docker exec sentinel-freqtrade freqtrade backtesting --strategy VolatilityBreakout
# Syarat: profit factor >= 1.2, drawdown wajar, fee sudah dihitung

# 3. Dry-run minimal 1-2 minggu, pantau via Telegram (/daily, /profit)

# 4. Baru live dengan modal kecil:
#    ubah "dry_run": false di config.json (API key exchange: JANGAN beri
#    permission withdraw — trading saja)
```

---

## Perintah

```bash
sentinel demo                          # simulasi end-to-end (tanpa exchange/key)
sentinel doctor                        # cek: python, brain, freqtrade, secret
sentinel run --config config.yml       # loop orkestrasi paper-mode
sentinel run --config config.yml --once # satu siklus saja
sentinel version
./scripts/deploy_strategy.sh [user_data_dir]
```

---

## Struktur repo

```
sentinel/            core: bus, risk, orchestrator, validation, strategies, cli
adapters/            jembatan ke TradingAgents (brain) & Freqtrade (eksekusi)
workers/             arb_worker - arbitrase market-neutral (liquidity filter)
strategies_ft/       strategi Freqtrade siap deploy (VolatilityBreakout)
tests/               smoke test + e2e (wajib lolos sebelum dipakai)
bootstrap.sh         SATU script setup otomatis
config.example.yml   contoh config orkestrasi
docker-compose.yml   template full-stack
```

---

## Batasan & kejujuran

- Menumpuk 6 framework **tidak mengalikan win rate**. Win rate milik strategi +
  kondisi market. Yang ditambah sistem ini: disiplin eksekusi, validasi bukti,
  dan manajemen risiko berlapis.
- 70–80% bot ritel gagal dalam 12 bulan, umumnya karena strategi tidak adaptif
  terhadap perubahan regime — itulah yang coba diatasi orchestrator ini, tapi
  tidak ada jaminan.
- Software ini untuk edukasi. Jangan pakai uang yang tidak siap hilang.
  Selalu mulai dari dry-run.

---

## Troubleshooting

| Gejala | Solusi |
|---|---|
| `sentinel: command not found` | `pip install .` belum jalan / `~/.local/bin` belum di PATH |
| `docker: command not found` | install Docker dulu: https://docs.docker.com/get-docker/ |
| Freqtrade tidak bisa diakses :8080 | cek `docker ps`; pastikan api_server enabled di config.json |
| Brain "not found" | set `SENTINEL_TA_DIR` ke folder tradingagents (atau biarkan mode simulasi) |
| Backtest jelek | JANGAN live. Tuning parameter → backtest lagi → baru dry-run |

---

## Lisensi

MIT untuk kode Sentinel. **Catatan:** Freqtrade berlisensi GPL-3.0 — jika
mendistribusikan gabungan yang mencakup kodenya, patuhi GPL. Pemakaian privat
aman.
