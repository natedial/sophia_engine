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

## Deployment Options (AWS)

Recommendation: For AWS choose the smallest viable path now and evolve as load grows.

Option A: Single EC2 + systemd (fastest to ship)
- Run each service as a systemd unit (scrivener, sophia_arithmos, sophia_kampe, sophia_prima).
- Put Nginx in front if you need a single public entrypoint.
- Use CloudWatch Agent for logs/metrics.

Option B: ECS Fargate (managed, scalable)
- Containerize each service and deploy as separate ECS tasks.
- Use an ALB for routing and TLS termination.
- Centralize logs in CloudWatch; add autoscaling as needed.

Option C: EKS (only if you already run k8s)
- Full Kubernetes stack; highest ops overhead.
- Not recommended unless you have existing k8s ops.

Notes
- Keep Supabase as the primary DB and central vector store.
- Give parser/sophia services read-only DB roles where possible.
- Start with small instance sizes and add autoscaling once traffic is known.
