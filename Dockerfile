FROM python:3.12-slim
WORKDIR /app
COPY sentinel ./sentinel
COPY adapters ./adapters
COPY workers ./workers
# No heavy deps: core is stdlib-only. ccxt/pandas only needed on workers
# that talk to real exchanges.
CMD ["python3", "-m", "sentinel.orchestrator"]
