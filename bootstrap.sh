#!/bin/bash
# ==============================================================================
# Sentinel bootstrap - SATU script untuk semuanya, berurutan, otomatis.
#
#   ./bootstrap.sh                 full setup + backtest? no, + langsung jalan (dry-run)
#   ./bootstrap.sh --backtest      + backtest strategi sebelum jalan
#   ./bootstrap.sh --no-run        setup saja, jangan langsung jalan
#   ./bootstrap.sh --dry-run       cuma tampilkan apa yang AKAN dilakukan
#   ./bootstrap.sh --yes           non-interaktif (pakai env/default)
#
# Env yang dipakai (opsional):
#   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  -> notifikasi Telegram Freqtrade
#   FT_USER, FT_PASS                   -> login api_server Freqtrade
#   EXCHANGE                            -> default: binance
# ==============================================================================
set -e
cd "$(dirname "$0")"

BACKTEST=0; RUN=1; DRY=0; YES=0
for a in "$@"; do
  case "$a" in
    --backtest) BACKTEST=1 ;;
    --no-run)   RUN=0 ;;
    --dry-run)  DRY=1 ;;
    --yes)      YES=1 ;;
    *) echo "flag tidak dikenal: $a"; exit 1 ;;
  esac
done

step() { echo; echo "=== [$1] $2 ==="; }
run()  { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }
ask()  { # ask <var> <prompt> <default>
  if [ "$YES" = 1 ]; then eval "$1=\${$1:-$3}"; return; fi
  local cur; eval "cur=\$$1"
  if [ -n "$cur" ]; then return; fi
  read -r -p "$2 [$3]: " val
  eval "$1=\"${val:-$3}\""
}
die()  { echo "ERROR: $1" >&2; exit 1; }

if [ "$(id -u)" = 0 ]; then
  echo "WARNING: jalan sebagai root (sudo). Disarankan jalan sebagai user biasa"
  echo "         (masukkan user ke grup docker: sudo usermod -aG docker \$USER)."
  echo "         Lanjut dalam 5 detik... (Ctrl+C untuk batal)"
  [ "$DRY" = 1 ] || [ "$YES" = 1 ] || sleep 5
fi

[ -f pyproject.toml ] || die "jalankan dari root repo sentinel-trading (pyproject.toml tidak ketemu)"

step 1 "Cek prasyarat"
command -v python3 >/dev/null || die "python3 tidak ketemu"
PYV=$(python3 -c 'import sys; print(sys.version_info.major*100+sys.version_info.minor)')
[ "$PYV" -ge 311 ] || die "butuh Python >= 3.11 (ketemu: $(python3 --version))"
command -v git >/dev/null || die "git tidak ketemu"
if ! command -v docker >/dev/null; then
  [ "$DRY" = 1 ] || die "docker tidak ketemu - install dulu: https://docs.docker.com/get-docker/"
  echo "  (dry-run: anggap docker ada)"
fi
echo "  python $(python3 --version | cut -d' ' -f2) OK"

step 2 "Install package sentinel"
PIP_BIN=""
for c in pip pip3; do
  if command -v "$c" >/dev/null 2>&1; then PIP_BIN="$c"; break; fi
done
[ -n "$PIP_BIN" ] || die "pip tidak ketemu - install dulu: sudo apt install python3-pip"
echo "  pakai: $PIP_BIN"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] $PIP_BIN install ."
else
  if ! $PIP_BIN install . 2>/tmp/sentinel-pip.log; then
    echo "  --- coba lagi dengan --break-system-packages ---"
    if ! $PIP_BIN install --break-system-packages . 2>/tmp/sentinel-pip.log; then
      echo "  --- error pip ---"
      tail -15 /tmp/sentinel-pip.log
      die "pip install gagal - atau pakai virtualenv: python3 -m venv .venv && source .venv/bin/activate && ./bootstrap.sh"
    fi
  fi
fi
command -v sentinel >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
command -v sentinel >/dev/null 2>&1 || [ "$DRY" = 1 ] \
  || die "perintah 'sentinel' tidak ketemu setelah install - cek PATH (mungkin di ~/.local/bin)"
echo "  sentinel terinstall"

step 3 "Test otomatis (wajib lolos)"
run python3 tests/test_sentinel.py

step 4 "Config"
[ -f config.yml ] || run cp config.example.yml config.yml
[ -f config.yml ] || true
echo "  config.yml siap (sesuaikan ticker & alokasi kalau perlu)"

step 5 "Deploy strategi ke Freqtrade user_data"
USER_DATA="${HOME}/.freqtrade/user_data"
run mkdir -p "$USER_DATA/strategies"
run ./scripts/deploy_strategy.sh "$USER_DATA"

step 6 "Pull image Freqtrade"
run docker pull freqtradeorg/freqtrade:stable

step 7 "Config Freqtrade (config.json)"
EXCHANGE="${EXCHANGE:-binance}"
ask TELEGRAM_TOKEN "Telegram bot token (@BotFather, kosongkan=nonaktif)" ""
ask TELEGRAM_CHAT_ID "Telegram chat_id (@userinfobot, kosongkan=nonaktif)" ""
ask FT_USER "Username api_server Freqtrade" "sentinel"
if [ -z "${FT_PASS:-}" ] && [ "$YES" = 0 ] && [ "$DRY" = 0 ]; then
  read -r -s -p "Password api_server Freqtrade [random]: " FT_PASS; echo
fi
FT_PASS="${FT_PASS:-$(head -c12 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c16)}"
export TELEGRAM_TOKEN TELEGRAM_CHAT_ID FT_USER FT_PASS EXCHANGE USER_DATA
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] generate $USER_DATA/config.json"
else
  python3 - "$USER_DATA/config.json" <<'PYEOF'
import json, os, sys
cfg_path = sys.argv[1]
cfg = {
  "max_open_trades": 3,
  "stake_currency": "USDT",
  "stake_amount": 100,
  "tradable_balance_ratio": 0.99,
  "fiat_display_currency": "USD",
  "dry_run": True,
  "cancel_open_orders_on_exit": True,
  "timeframe": "15m",
  "exchange": {"name": os.environ["EXCHANGE"], "pair_whitelist": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]},
  "telegram": {"enabled": bool(os.environ.get("TELEGRAM_TOKEN")),
               "token": os.environ.get("TELEGRAM_TOKEN", ""),
               "chat_id": os.environ.get("TELEGRAM_CHAT_ID", "")},
  "api_server": {"enabled": True, "listen_ip_address": "127.0.0.1",
                 "listen_port": 8080, "username": os.environ["FT_USER"],
                 "password": os.environ["FT_PASS"]},
  "bot_name": "sentinel",
  "initial_state": "running",
  "db_url": "sqlite:////freqtrade/user_data/tradesv3.sqlite",
}
os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
with open(cfg_path, "w") as f:
  json.dump(cfg, f, indent=2)
print("  config.json ditulis")
PYEOF
fi
echo "  api_server user: $FT_USER (password tersimpan di env, tidak ditulis di repo)"

step 8 "Download data historis"
FROM=$(date -d '90 days ago' +%Y%m%d 2>/dev/null || date -v-90d +%Y%m%d)
TO=$(date +%Y%m%d)
run docker run --rm -v "$USER_DATA:/freqtrade/user_data" freqtradeorg/freqtrade:stable \
  download-data --exchange "$EXCHANGE" --timeframes 15m \
  --pairs BTC/USDT ETH/USDT SOL/USDT -t "${FROM}-${TO}"

if [ "$BACKTEST" = 1 ]; then
  step 9 "Backtest VolatilityBreakout"
  run docker run --rm -v "$USER_DATA:/freqtrade/user_data" freqtradeorg/freqtrade:stable \
    backtesting --config /freqtrade/user_data/config.json \
    --strategy VolatilityBreakout -t "${FROM}-${TO}"
  echo "  -> cek hasilnya di atas. Lolos? (profit factor >= 1.2, drawdown wajar)"
  echo "     Kalau belum lolos: JANGAN live. Tuning dulu, ulangi backtest."
fi

step 10 "Jalankan Freqtrade (dry-run)"
run docker rm -f sentinel-freqtrade >/dev/null 2>&1 || true
run docker run -d --name sentinel-freqtrade --restart unless-stopped \
  -p 8080:8080 -v "$USER_DATA:/freqtrade/user_data" \
  freqtradeorg/freqtrade:stable trade \
  --config /freqtrade/user_data/config.json --strategy VolatilityBreakout --dry-run

step 11 "Cek kesehatan"
run sentinel doctor || true

echo
echo "============================ RINGKASAN ============================"
echo "  Freqtrade  : http://127.0.0.1:8080 (dry-run, user: $FT_USER)"
[ -n "$TELEGRAM_TOKEN" ] && echo "  Telegram   : aktif - coba /profit di bot lu" || echo "  Telegram   : nonaktif (isi TELEGRAM_TOKEN kalau mau)"
echo "  Strategi   : VolatilityBreakout (15m, BTC/ETH/SOL)"
if [ -x "$HOME/tradingagents/ta.sh" ]; then
  echo "  Brain      : ketemu di ~/tradingagents -> dipakai otomatis"
  export SENTINEL_TA_DIR="$HOME/tradingagents"
else
  echo "  Brain      : ~/tradingagents tidak ketemu -> mode simulasi"
fi
echo "=================================================================="

if [ "$RUN" = 1 ]; then
  echo
  echo "Menjalankan orkestrasi paper-mode (Ctrl+C untuk berhenti)..."
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] SENTINEL_FT_URL=http://127.0.0.1:8080 sentinel run --config config.yml"
  else
    export SENTINEL_FT_URL="http://127.0.0.1:8080"
    export SENTINEL_FT_USER="$FT_USER" SENTINEL_FT_PASS="$FT_PASS"
    exec sentinel run --config config.yml
  fi
else
  echo
  echo "Setup selesai. Untuk jalan manual:"
  echo "  export SENTINEL_FT_URL=http://127.0.0.1:8080 SENTINEL_FT_USER=$FT_USER SENTINEL_FT_PASS=<password>"
  [ -x "$HOME/tradingagents/ta.sh" ] && echo "  export SENTINEL_TA_DIR=\$HOME/tradingagents"
  echo "  sentinel run --config config.yml"
fi
