# Architecture

Clients → LiteLLM Proxy → CustomLLM → CodexBackend → RPCClient → Transport → external Codex.
No independent HTTP adapter and no LiteLLM core changes. The package is independently
authored because reference licensing is unresolved.

Each provider lazily owns a worker event loop; sync calls submit futures and async calls
await wrapped futures. Both streaming interfaces request one event at a time. A semaphore
limits active turns per provider/process. Each request opens a fresh initialized connection,
creates an ephemeral thread and executes one turn. Independent connections and thread/turn
filters prevent cross-request event leakage. Correlation IDs and pending futures handle RPC
responses; notifications enter a 64-event bounded queue. Overflow fails the request rather
than silently dropping output or blocking the response reader. WebSocket buffers are also bounded.

Connection reuse is deliberately deferred. Reconnection means establishing a fresh connection
for a subsequent request; no request or turn is replayed. Setting auto reconnect false latches
connection failures until the provider is recreated. Disable LiteLLM router retries too.
Request deadline includes semaphore admission, handshake and execution. Cancellation sends a
best-effort interrupt and closes the connection; this cannot prove a remote turn has stopped.

The backend interface provides completion, stream, model listing, health and close. Only RPC is
implemented. Direct mode and stateful mode fail explicitly. Transport and converters do not
read credentials. Each worker process owns independent resources and concurrency limits.

INFO logs contain request ID, backend, transport, thread/turn IDs, duration, first-token time
and terminal status. They exclude prompts, tokens, remote exception text and filesystem paths.
RPC method latency metrics, durable sessions and distributed worker limits remain
follow-up work. No token count is estimated: usage is populated only from backend token events.
