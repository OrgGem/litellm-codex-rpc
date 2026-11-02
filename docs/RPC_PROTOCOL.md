# Protocol evidence

Authoritative local executable: `codex-cli 0.163.0`. On 2026-11-03:

```sh
codex app-server --help
codex app-server generate-json-schema --out /tmp/codex-schema
```

Unix listeners accept **WebSocket over Unix sockets**, verified with an actual initialize
request. A newline-delimited probe did not yield a response. TCP WebSocket and stdio both
passed real initialize/account/read exchanges. stdio uses one JSON envelope per line.
These transports are experimental and version dependent; other Codex versions are untested.

Envelopes use `id`, `method`, `params`, `result`/`error`; no `jsonrpc: 2.0` field is required.
Handshake: initialize(clientInfo{name,version}), then initialized notification. Required:
thread/start → thread.id; turn/start(threadId,input[{type:"text",text}]) → turn.id.
Agent deltas use item/agentMessage/delta(threadId,turnId,itemId,delta).
turn/completed has threadId and turn{id,status,error}. Only completed is success; interrupted
and failed are errors. thread/tokenUsage/updated.tokenUsage.last is used when supplied.
All server-initiated requests receive -32601 and fail the active request. No approval is granted.
turn/interrupt is attempted on cancellation/deadline. account/read(refreshToken:false) checks
server auth state; the provider never receives OAuth token data. model/list is exposed on the
backend but alias availability is ultimately validated by Codex on turn creation.

thread/start requests read-only sandbox and untrusted approval policy, with shell_tool,
unified_exec and apply_patch_freeform disabled and web_search disabled via config overrides.
These keys were checked against the official Codex config schema:
https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json
This does not disable every possible runtime capability; dedicated server isolation is required.

For protocol changes regenerate schemas and validate outgoing params and recorded notification
fixtures before upgrading the pinned runtime. Tests using mocks are not proof of a live turn.
A real authenticated Unix turn timed out; a stdio diagnostic turn disconnected after turn/started.
No complete live model response has been verified in this environment.
