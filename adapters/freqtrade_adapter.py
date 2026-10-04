"""Execution adapter - Freqtrade REST API client (stdlib only).

Freqtrade exposes a REST API (default http://127.0.0.1:8080). Enable it in
freqtrade config:
  "api_server": {"enabled": true, "listen_ip_address": "127.0.0.1",
                 "listen_port": 8080, "username": "...", "password": "..."}

Sentinel uses it to: read status/profit, start/stop the bot, force-exit.
Strategy code itself lives in strategies_ft/ and is deployed to freqtrade's
user_data/strategies/.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request


class FreqtradeClient:
    def __init__(self, base_url: str | None = None,
                 username: str | None = None, password: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("SENTINEL_FT_URL",
                         "http://127.0.0.1:8080")).rstrip("/")
        user = username or os.environ.get("SENTINEL_FT_USER", "")
        pw = password or os.environ.get("SENTINEL_FT_PASS", "")
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}",
                         "Content-Type": "application/json"}

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body or {}).encode() if body is not None else None,
            headers=self._headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    # -- reads -----------------------------------------------------------
    def status(self): return self._call("GET", "/api/v1/status")
    def profit(self): return self._call("GET", "/api/v1/profit")
    def balance(self): return self._call("GET", "/api/v1/balance")

    # -- control ---------------------------------------------------------
    def start(self): return self._call("POST", "/api/v1/start")
    def stop(self): return self._call("POST", "/api/v1/stop")
    def stop_entry(self): return self._call("POST", "/api/v1/stopentry")
    def forceexit(self, trade_id: str = "all"):
        return self._call("POST", "/api/v1/forceexit",
                          {"tradeid": trade_id})
