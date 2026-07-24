# Runbook

Local dev run instructions for the Sophia stack.

## One-Time Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate

cd services/scrivener && pip install -e .
cd ../sophia_arithmos && pip install -e .
cd ../sophia_kampe && pip install -e .
cd ../sophia_oikonomia && pip install -e .
cd ../sophia_sentry && pip install -e .
cd ../sophia_pylon && pip install -e ".[mcp]"
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
cd services/sophia_oikonomia
python -m sophia_oikonomia
```

```bash
source .venv/bin/activate
cd services/sophia_sentry
python -m sophia_sentry
```

```bash
source .venv/bin/activate
cd services/sophia_pylon
PYLON_MCP_HOST=127.0.0.1 PYLON_MCP_PORT=8091 sophia-pylon-mcp
```

```bash
source .venv/bin/activate
curl http://localhost:8091/health
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
- `http://localhost:8006` sophia_oikonomia
- `http://localhost:8003` sophia_canvas
- `http://localhost:13000` sophia_dashboard
- `http://localhost:8091/mcp` sophia_pylon_mcp

Pylon MCP endpoints:
- `GET /health`
- `POST /mcp` (Streamable HTTP MCP)

Pylon MCP configuration:
- Hermes on the same machine: `http://localhost:8091/mcp`.
- The host port binds to `127.0.0.1` by default through `PYLON_MCP_BIND_ADDRESS`.
- Set `BRAVE_API_KEY` in `infra/.env` to enable live web tools.
- Verify degraded services with the `sophia_pylon_preflight` MCP tool.
- Do not expose the MCP port directly to the public internet. Prefer Tailscale (below); never router port-forward `8091`.

### Tailscale: Hermes on another machine

Use when Hermes runs on a different host on the same Tailscale network.

1. In `infra/.env`, set:

   ```bash
   PYLON_MCP_BIND_ADDRESS=0.0.0.0
   ```

2. Recreate the MCP container so the publish address takes effect:

   ```bash
   make up
   # or from infra/: docker compose up -d --force-recreate sophia_pylon_mcp
   ```

3. On the Sophia host, note the Tailscale address (`tailscale ip -4` or MagicDNS name).

4. From the Hermes host, verify health over the tailnet:

   ```bash
   curl http://<sophia-magicdns-or-100.x>:8091/health
   ```

   Expected: `{"status":"ok","mcp_path":"/mcp"}`.

5. Point Hermes at:

   ```yaml
   mcp_servers:
     sophia:
       url: "http://<sophia-magicdns-or-100.x>:8091/mcp"
       tools:
         include:
           - "*"
   ```

6. Ask Hermes to call `sophia_pylon_preflight` before deeper jobs.

Notes:
- Binding `0.0.0.0` publishes on all host interfaces. Rely on Tailscale (and no public port-forward) as the access boundary for this profile.
- Keep the default `127.0.0.1` bind for same-machine local testing.

## Deployment Options (AWS)

Recommendation: For AWS choose the smallest viable path now and evolve as load grows.

Option A: Single EC2 + systemd (fastest to ship)
- Run each service as a systemd unit (scrivener, sophia_arithmos, sophia_kampe, sophia_oikonomia, sophia_pylon_mcp).
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
