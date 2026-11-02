# Compatibility and acceptance evidence

Validated 2026-11-03. This is an experimental MVP, **not complete acceptance** of the BRD.

| Capability | Evidence | Status |
|---|---|---|
| Reference licensing and reuse matrix | Source audit at 4390c73; no upstream license | Complete audit; no source copied |
| Standard package installation | Editable install; Hatchling sdist and wheel builds | Pass |
| LiteLLM 1.80.7 four CustomLLM methods | Signature inspection, real SDK dispatch, sync inside existing loop | Pass for keyword dispatch |
| Codex 0.163.0 Unix framing | Real WebSocket initialization; raw-line negative probe | Pass |
| Codex Unix, TCP WebSocket, stdio handshake | Real initialize, initialized, account/read | Pass; authenticated account reported |
| Live authenticated text turn | Unix timed out; diagnostic stdio disconnected after turn/started | BLOCKED: no completed live text response; cause unresolved |
| Text completion and HTTP SSE | Local fixture, real LiteLLM SDK and Proxy HTTP process | Pass against fixture |
| Proxy authentication | HTTP missing key rejected | Pass |
| Error mapping | HTTP unsupported tools 400; fixture rate limit 429 | Pass |
| Five isolated concurrent streams | Unix and TCP WebSocket fixtures, unique threads | Pass against fixture |
| Correlation, timeout, cancellation, recovery | Reordered RPC replies, pending timeout, explicit interrupt, future request after disconnect | Pass against fixture |
| Protocol parameter shapes | scripts/verify_protocol.py against generated 0.163.0 schemas | Pass |
| History and system/developer roles | Ordered text flattening opt-in only | Limited; no exact role equivalence |
| Models | Configurable aliases; backend model/list method | Alias validation implemented; live entitlement selection unverified |
| Usage | Uses tokenUsage.last only when supplied | Conversion implemented; live usage unverified |
| Stateful sessions, dynamic tools, images, Responses API | Explicit rejection/deferred | Unsupported |
| Legacy direct backend | Licensing gate | Unavailable |
| Internal tool confinement | Disabled execution flags, read-only sandbox, reject all server requests | Defense in depth; dedicated server OS isolation required |
| Remote WebSocket auth/TLS | Configuration implemented | Not live-tested |
| Docker | Built image; nonroot Proxy HTTP completion + SSE through shared Unix fixture socket | Pass against fixture; live model not tested |
| Hermes/OpenCode/n8n | No live client runs | Unverified |

## Release gate

A working authenticated external Codex server must finish a text turn through this provider.
An account/read result alone does not establish usable model access. The installed runtime
started threads and turns, but supplied no complete response during validation. No auth file
was inspected or token extracted. Configure a known working service endpoint and rerun the
live check before marking phases 0–3 accepted. Do not claim production security or full client
compatibility from the fixture suite. See SECURITY.md for remaining runtime isolation requirements.

## Repeatable checks

`pytest -q` runs 19 unit/integration/Proxy checks with local fixtures (no model usage).
`python scripts/verify_protocol.py` requires installed Codex and checks generated schemas.
`python scripts/container_smoke.py` requires Docker and the built 0.2.0 image; it uses fixture
responses over a shared Unix socket, not subscription resources.

Container smoke completed successfully with the final image, including nonroot config access and group-restricted socket access. No credentials were mounted into the Proxy container.
