# Sophia With Hermes

This note captures where the Hermes cutover work left off and how to test it later.

## Current State

- PR: https://github.com/natedial/sophia_engine/pull/2
- Branch: `hermes-deploy`
- Sophia now exposes Pylon tools through a Streamable HTTP MCP server.
- Hermes is intended to own the agent loop, memory, session handling, and user-facing gateway.
- Sophia remains responsible for backend services, tools, data access, computation, research, and canvas operations.
- The old `sophia_gateway` / `sophia_prima` path is intentionally out of scope for this launch test; Hermes owns orchestration.

## Local Sophia Startup

From the repo root:

```bash
git checkout hermes-deploy
make up
```

Default MCP endpoint:

```text
http://localhost:8091/mcp
```

Health check:

```bash
curl http://localhost:8091/health
```

Expected:

```json
{"status":"ok","mcp_path":"/mcp"}
```

## Hermes MCP Config

If Hermes runs on the same machine:

```yaml
mcp_servers:
  sophia:
    url: "http://localhost:8091/mcp"
    tools:
      include:
        - "*"
```

If Hermes runs on another machine over Tailscale (recommended remote profile):

1. On the Sophia host, in `infra/.env`:

   ```bash
   PYLON_MCP_BIND_ADDRESS=0.0.0.0
   ```

2. Recreate the stack / MCP container (`make up` or force-recreate `sophia_pylon_mcp`).

3. Point Hermes at the Sophia Tailscale MagicDNS name or `100.x` address:

```yaml
mcp_servers:
  sophia:
    url: "http://<sophia-magicdns-or-100.x>:8091/mcp"
    tools:
      include:
        - "*"
```

4. From the Hermes host, confirm `curl http://<sophia-magicdns-or-100.x>:8091/health` before deeper tests.

Do not router port-forward `8091`. This profile assumes a private Tailscale network as the access boundary.

## First Validation Pass

Start with a tight tool smoke test. The goal is to see whether Hermes naturally discovers and sequences Sophia tools without us rebuilding orchestration around it.

1. Ask Hermes to call:

   ```text
   sophia_pylon_preflight
   ```

   Confirm it reports service health, available tools, and unavailable tools.

2. Try an economic data lookup.

   Example prompt:

   ```text
   Use Sophia tools to get the latest value for GDP or FEDFUNDS.
   ```

3. Try a computation.

   Example prompt:

   ```text
   Use Sophia tools to compute summary statistics on a small time series.
   ```

4. Try research search if Tholos has a corpus mounted.

   Example prompt:

   ```text
   Use Sophia research tools to search the local corpus for recent Fed communication about inflation.
   ```

5. Try Canvas/chart behavior if you want to validate artifact workflows.

   Example prompt:

   ```text
   Use Sophia tools to create a simple time-series chart for FEDFUNDS.
   ```

## Next Readiness Pass

The next step is an end-to-end Hermes readiness pass, not more repo cleanup.

1. Run the full compose stack.

   ```bash
   cp infra/.env.example infra/.env
   make up
   make ps
   ```

2. Verify the MCP surface locally.

   ```bash
   curl http://localhost:8091/health
   ```

   Then connect Hermes or another MCP client to:

   ```text
   http://localhost:8091/mcp
   ```

3. Have Hermes call `sophia_pylon_preflight` first.

   Treat this as the default diagnostic before deeper jobs. It should report which Sophia services are healthy, degraded, or unavailable.

4. Smoke test representative jobs through Hermes.

   - Fetch or summarize data through Scrivener.
   - Run an Arithmos calculation.
   - Search/query the Tholos corpus.
   - Create or inspect Canvas state.
   - Hit Oikonomia tools.
   - Try a live web tool with `BRAVE_API_KEY` set.
   - Try Readwise if `.readwise-cli.json` is mounted.

5. Enable Tailscale reachability if Hermes is on another host.

   Set `PYLON_MCP_BIND_ADDRESS=0.0.0.0` in `infra/.env`, recreate `sophia_pylon_mcp`, then verify health and `sophia_pylon_preflight` from the Hermes machine over Tailscale. See `docs/runbook.md` (Tailscale section). Do not publicly expose `8091`.

6. Add launch guardrails.

   - Add a short Hermes tool-use prompt telling it to call preflight first.
   - Add a small MCP smoke test script.
   - Add a runbook section for failed service dependencies.
   - Keep the deployment warning explicit: do not expose unauthenticated MCP publicly.

## Key Considerations

- This is a deliberate trade: Hermes owns orchestration; Sophia owns tools/core logic.
- Do not try to recreate `sophia_prima` inside a Hermes adapter. That would bring the orchestration burden back.
- The v1 MCP bridge does not preserve Prima-specific features:
  - `AgentEvent` streaming
  - Gateway run-store diagnostics
  - Sophia memory/history semantics
  - custom research citation repair
  - presentation policy and artifact resolver behavior
  - Sophia subagent orchestration
- If any of those turn out to be essential, add them back as focused Sophia tools or lightweight MCP resources, not as a second agent loop.
- Treat `sophia_pylon_preflight` as the first diagnostic any time Hermes seems confused. If services are unavailable, Hermes should be told to call preflight before attempting deeper workflows.
- Tool names and schemas come from Pylon dynamically. Adding a new Sophia capability should usually mean adding a Pylon tool, not changing Hermes.
- If Hermes runs on another host, use the Tailscale profile (`PYLON_MCP_BIND_ADDRESS=0.0.0.0`) and Hermes URL `http://<sophia-magicdns-or-100.x>:8091/mcp`. Confirm health from the Hermes host before blaming tool failures.
- The MCP endpoint is intended for local/Tailscale access. Default compose bind is `127.0.0.1`; the Tailscale profile binds `0.0.0.0` but must not be router port-forwarded or exposed on the public internet.
- Readwise depends on the mounted CLI config. If Readwise tools fail, verify `.readwise-cli.json` is mounted and the path matches `READWISE_CLI_CONFIG_PATH`.
- Tholos research depends on `RESEARCH_CORPUS_PATH`. If corpus tools are unavailable, check the mounted corpus path and run `sophia_pylon_preflight`.
- Brave/live web tools require `BRAVE_API_KEY`.
## What To Decide After Testing

After the first Hermes run, decide based on behavior, not just connectivity:

- Does Hermes discover the right Sophia tools without much prompting?
- Does it chain data lookup -> computation -> synthesis reliably?
- Does it handle unavailable services gracefully after preflight?
- Are Hermes memory/session defaults good enough to stop investing in Prima memory/history?
- Are any Prima-only behaviors actually product-critical, or can they remain retired?

If the answer is mostly yes, the next step is to merge the PR and make Pylon MCP the default agent-facing surface.
