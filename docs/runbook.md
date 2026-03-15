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
source .venv/bin/activate
cd services/scrivener
scrivener serve --port 8000
```

```bash
source .venv/bin/activate
cd services/sophia_arithmos
python -m sophia_arithmos.main
```

```bash
source .venv/bin/activate
cd services/sophia_kampe
python -m sophia_kampe.main
```

```bash
source .venv/bin/activate
cd services/sophia_pylon
# No standalone server; consumed by sophia_prima
```

```bash
source .venv/bin/activate
cd agents/sophia_prima
python -m sophia.cli
```

## Docker Compose

```bash
make up
```

Optional: set `FRED_API_KEY` and `BLS_API_KEY` in `infra/.env` if you want Scrivener to fetch data.

Other commands:
- `make logs`
- `make ps`
- `make down`

Service URLs:
- `http://localhost:8000` scrivener
- `http://localhost:8001` sophia_arithmos
- `http://localhost:8002` sophia_kampe
- `http://localhost:8003` sophia_canvas
- `http://localhost:13000` sophia_dashboard
- `http://localhost:18080` sophia_gateway

Gateway endpoints:
- `GET /health`
- `POST /v1/messages` (channel-agnostic ingress)
- `WS /ws` (connect handshake + typed frames)

Gateway configuration:
- Set `OPENAI_API_KEY` in `infra/.env` for real model responses.
- Optional: set `LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` to switch provider.
- Optional: set `LLM_PROVIDER=groq` plus `GROQ_API_KEY` to switch provider.
- `PERSONALITY_PATH` and `SOUL_PATH` control the agent prompt components loaded by gateway.
- Set `TELEGRAM_BOT_TOKEN` (single bot) or `TELEGRAM_ACCOUNTS_JSON` (multi-bot).
- Optional deterministic bindings via `GATEWAY_BINDINGS_JSON`.
- Optional Codex-backed delegated coding: set `DEV_WORKER_ENABLED=true` and point
  `DEV_WORKER_WORKSPACE_ROOT` at the repo/worktree you want the worker to edit.
- If `dev_worker` is enabled, widen `AGENT_FS_READ_ALLOWLIST` and
  `AGENT_FS_WRITE_ALLOWLIST` to include that workspace root, or the worker will be denied by policy.

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
