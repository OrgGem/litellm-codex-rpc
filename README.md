# LiteLLM Codex RPC Provider

Experimental independent Python implementation of the 0.2.0 RPC MVP. Codex App
Server owns authentication and execution; this plugin never reads Codex OAuth files.
See [compatibility](docs/COMPATIBILITY.md), [audit](docs/REFERENCE_AUDIT.md),
[protocol](docs/RPC_PROTOCOL.md) and [security](docs/SECURITY.md).

## Install and run

Python 3.11+, Codex CLI **0.163.0**, LiteLLM **1.80.7**.

```sh
pip install '.[proxy]'
# In the separate Codex runtime, authenticate using its normal supported login.
codex login
# Use a dedicated empty working directory and dedicated, restricted Codex configuration.
umask 0077
codex app-server --listen unix:///run/codex/codex.sock
# In the LiteLLM runtime (no Codex auth directory mount):
export CODEX_BACKEND=rpc
export CODEX_RPC_TRANSPORT=unix
export CODEX_RPC_SOCKET_PATH=/run/codex/codex.sock
export CODEX_MODEL_MAP='{"codex-default":null}'
export LITELLM_MASTER_KEY='<your-own-proxy-key>'
litellm --config config.example.yaml --port 4000
```

Keep `proxy_handler.py` beside the YAML file: LiteLLM 1.80.7 resolves handlers relative to configuration. The shim imports the installed package.

Create `/run/codex` owned by the Codex user first. Grant only the LiteLLM user/group
access. Run server outside the plugin process; use a process supervisor. `null` model
selects the server default; configure real model IDs for additional aliases.

```sh
curl http://localhost:4000/v1/chat/completions \
 -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
 -d '{"model":"codex-default","messages":[{"role":"user","content":"Say hello"}],"stream":true}'
```

WebSocket alternative: `codex app-server --listen ws://127.0.0.1:4500`; set
`CODEX_RPC_TRANSPORT=websocket` and `CODEX_RPC_WS_URL=ws://127.0.0.1:4500`.
For remote hosts use a trusted network, TLS termination, and Codex's documented
`--ws-auth capability-token --ws-token-file ...` settings. Supply the matching
capability token via `CODEX_RPC_WS_TOKEN` securely. Remote plaintext is rejected.
This is a server access token, never an OAuth token. Remote auth is not live-tested.

Optional `CODEX_RPC_TRANSPORT=stdio` spawns `codex app-server --listen stdio://` per
request with noninteractive protocol input; Codex must be installed in that runtime.
Its stderr is discarded to protect request data. It is lower priority than shared sockets.

## Configuration

| Variable | Default |
|---|---|
| CODEX_BACKEND | rpc (direct rejected) |
| CODEX_RPC_TRANSPORT | unix |
| CODEX_RPC_SOCKET_PATH | /run/codex/codex.sock |
| CODEX_RPC_WS_URL | empty |
| CODEX_RPC_CONNECT_TIMEOUT | 10 seconds |
| CODEX_RPC_REQUEST_TIMEOUT | 300 seconds including queue wait |
| CODEX_RPC_MAX_CONCURRENT_TURNS | 5 per provider instance/process |
| CODEX_RPC_AUTO_RECONNECT | true (new requests only; no replay) |
| CODEX_RPC_SESSION_MODE | stateless (stateful rejected) |
| CODEX_RPC_ALLOW_INTERNAL_TOOLS | false (true rejected) |
| CODEX_RPC_ALLOW_PROMPT_FLATTENING | false |
| CODEX_MODEL_MAP | {"codex-default":null} |

Default accepts one user text message. History, assistant and system/developer
messages require explicit prompt flattening. That mode preserves ordered JSON text,
but **does not provide exact role semantics**. No prior history is injected twice.
Tools, multimodal input, structured output, sampling and token-limit parameters are
rejected. Empty string content is preserved. Unknown aliases fail before execution.

Register from Python using `litellm.custom_provider_map = [{"provider":"codex_rpc",
"custom_handler":codex_rpc_provider}]` after importing the instance from
`litellm_codex_rpc`. Call `close()` / `await aclose()` on shutdown. Instantiate providers
after worker fork. Sync streaming is incremental, including when called within an
existing event loop; asynchronous calls execute on a dedicated provider loop.

## Development

```sh
pip install -e '.[dev,proxy]'
pytest
python -m build
```

Local fake-server tests prove framing, correlation, incremental output and failures;
they do not prove subscription access. Real initialization tests require a locally
installed Codex. Docker shared-socket completion and SSE passed against a local fixture. Authenticated
model completion and third-party clients still need separate acceptance runs. See compatibility matrix for current evidence.

Troubleshooting: connection errors mean check server version, socket permissions,
transport and service status. Initialization errors can mean protocol mismatch. A
terminal failure is never converted into a successful stop. Server error details are
kept out of public exceptions; inspect protected Codex logs for diagnosis. Slow consumers
fail explicitly on queue overflow rather than dropping text. No uncertain turn is replayed.

For the remaining live acceptance gate, point the documented environment variables at a known
working authenticated server, then run `python scripts/live_check.py`. This executes one model
turn and may consume account usage. It prints only success, never tokens or response text.
