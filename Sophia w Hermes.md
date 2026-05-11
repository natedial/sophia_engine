# Sophia With Hermes

This note captures where the Hermes cutover work left off and how to test it later.

## Current State

- PR: https://github.com/natedial/sophia_engine/pull/2
- Branch: `hermes-pylon-mcp-cutover`
- Sophia now exposes Pylon tools through a Streamable HTTP MCP server.
- Hermes is intended to own the agent loop, memory, session handling, and user-facing gateway.
- Sophia remains responsible for backend services, tools, data access, computation, research, and canvas operations.
- The old `sophia_gateway` / `sophia_prima` path is still present, but moved behind the `legacy-prima` Docker Compose profile.

## Local Sophia Startup

From the repo root:

```bash
git checkout hermes-pylon-mcp-cutover
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

Point Hermes at the Sophia MCP endpoint. If Hermes runs on a different machine, replace `localhost` with the host/IP where the Sophia stack is running.

```yaml
mcp_servers:
  sophia:
    url: "http://<sophia-host>:8091/mcp"
    tools:
      include:
        - "*"
```

If Hermes runs on the same machine:

```yaml
mcp_servers:
  sophia:
    url: "http://localhost:8091/mcp"
    tools:
      include:
        - "*"
```

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
- If Hermes runs on a home server and Sophia runs elsewhere, check firewall/NAT access to port `8091`.
- The MCP endpoint is currently unauthenticated. Do not expose it directly to the public internet without a private network, reverse proxy auth, VPN, or equivalent access control.
- Readwise depends on the mounted CLI config. If Readwise tools fail, verify `.readwise-cli.json` is mounted and the path matches `READWISE_CLI_CONFIG_PATH`.
- Tholos research depends on `RESEARCH_CORPUS_PATH`. If corpus tools are unavailable, check the mounted corpus path and run `sophia_pylon_preflight`.
- Brave/live web tools require `BRAVE_API_KEY`.
- The old Prima gateway can be started for rollback with the legacy profile:

  ```bash
  docker compose --env-file infra/.env -f infra/docker-compose.yml --profile legacy-prima up -d --build
  ```

## What To Decide After Testing

After the first Hermes run, decide based on behavior, not just connectivity:

- Does Hermes discover the right Sophia tools without much prompting?
- Does it chain data lookup -> computation -> synthesis reliably?
- Does it handle unavailable services gracefully after preflight?
- Are Hermes memory/session defaults good enough to stop investing in Prima memory/history?
- Are any Prima-only behaviors actually product-critical, or can they remain retired?

If the answer is mostly yes, the next step is to merge the PR and make Pylon MCP the default agent-facing surface.
