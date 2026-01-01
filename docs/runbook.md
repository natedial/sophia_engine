# Runbook

Local dev run instructions for the Sophia stack.

## One-Time Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate

cd services/scrivener && pip install -e .
cd ../sophia_arithmos && pip install -e .
cd ../sophia_kampe && pip install -e .
cd ../sophia_pylon && pip install -e .
cd ../../agents/sophia_prima && pip install -e .
```

## Start Services (separate shells)

```bash
source /Users/ndial/dev/sophia/.venv/bin/activate
cd /Users/ndial/dev/sophia/services/scrivener
scrivener serve --port 8000
```

```bash
source /Users/ndial/dev/sophia/.venv/bin/activate
cd /Users/ndial/dev/sophia/services/sophia_arithmos
python -m sophia_arithmos.main
```

```bash
source /Users/ndial/dev/sophia/.venv/bin/activate
cd /Users/ndial/dev/sophia/services/sophia_kampe
python -m sophia_kampe.main
```

```bash
source /Users/ndial/dev/sophia/.venv/bin/activate
cd /Users/ndial/dev/sophia/services/sophia_pylon
# No standalone server; consumed by sophia_prima
```

```bash
source /Users/ndial/dev/sophia/.venv/bin/activate
cd /Users/ndial/dev/sophia/agents/sophia_prima
python -m sophia.cli
```

## Docker Compose (stub)

```bash
cd /Users/ndial/dev/sophia/infra
cp .env.example .env
docker compose up --build
```
