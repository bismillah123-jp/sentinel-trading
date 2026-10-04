#!/bin/bash
# Deploy Sentinel's freqtrade strategies into a freqtrade user_data dir.
# Usage: ./scripts/deploy_strategy.sh [user_data_dir]
set -e
USER_DATA="${1:-$HOME/.freqtrade/user_data}"
mkdir -p "$USER_DATA/strategies"
cp strategies_ft/*.py "$USER_DATA/strategies/"
echo "deployed to $USER_DATA/strategies/"
ls "$USER_DATA/strategies/"
