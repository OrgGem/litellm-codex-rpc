# Reference audit

Audited `jslorrma/litellm-codex-oauth-provider` commit
`4390c73f3e6a13e423cbc5633c8e35455f728ae9` on 2026-11-03.

## Licensing gate
No LICENSE/COPYING file or package license declaration exists in this checkout.
Public availability does not grant redistribution rights. No reference implementation
or tests are copied. All implementation here is independent. Attribution here records
technical inspiration, not a claim that upstream code is licensed under this project's MIT license.
Legacy direct mode is unavailable pending licensing clarification and separate integration work.

Paths below are relative to the reference repository. Verified means source inspection,
not a successful live service test. Upstream tests were inspected, not executed.

| Component | Source file | Current behavior | Reuse decision | Reason | Test coverage and gaps | Target location |
|---|---|---|---|---|---|---|
| Provider | src/litellm_codex_oauth_provider/provider.py | CustomLLM with four completion/stream interfaces | Replace | License gate; backend separation needed | tests/unit/test_provider.py mocks HTTP; live compatibility unverified | provider.py |
| HTTP client | src/litellm_codex_oauth_provider/http_client.py | httpx POST /responses and incremental SSE iteration | Remove | RPC has no direct HTTP upstream | mocked integration SSE tests; no RPC tests | backends/rpc_backend.py |
| Authentication | src/litellm_codex_oauth_provider/auth.py | Opens auth.json, decodes account, token cache/refresh helpers | Remove | Forbidden in RPC mode | tests/unit/test_auth.py; README refresh claims do not establish live refresh | none |
| Request conversion | src/litellm_codex_oauth_provider/provider.py, prompts.py, openai_client.py | Builds responses payload, instructions and tool bridge; may filter prompts | Replace | Preserve input rather than silently filter; RPC input differs | tests/unit/test_transformations.py; fidelity gaps | converters/messages.py |
| Response conversion | src/litellm_codex_oauth_provider/adapter.py | Extracts output, tools, usage and finish reason | Replace | RPC event schema differs | transformation tests; terminal failure coverage unclear | converters/responses.py |
| Streaming | src/litellm_codex_oauth_provider/provider.py, sse_utils.py, streaming_utils.py | Async HTTP path incremental; sync streaming collects entire iterator | Replace | True sync and async incremental output required | unit SSE and mocked comprehensive integration tests; sync incrementality absent | provider.py |
| Function calling | src/litellm_codex_oauth_provider/prompts.py, streaming_utils.py, adapter.py | Tool bridge prompt and argument delta tracking | Remove | No faithful RPC caller-owned tool mapping verified | mocked tool conversion tests; Hermes/OpenCode live round trip unverified | explicit unsupported error |
| Model mapping | src/litellm_codex_oauth_provider/model_map.py | Hardcoded model families, alias/suffix normalization | Replace | User-configured aliases avoid entitlement assumptions | tests/unit/test_transformations.py | config.py |
| Errors | src/litellm_codex_oauth_provider/exceptions.py, provider.py | Auth exceptions; some streaming errors wrapped in RuntimeError | Replace | Structured safe external errors needed | mocked auth failures; disconnection semantics untested | errors.py |
| Deployment | docker-compose.yml, configs/litellm-config.yaml | main-latest proxy image, auth directory mount | Replace | Pin dependencies; RPC plugin receives socket only | No verified container execution | Dockerfile, docker-compose.yml |
| Build | pyproject.toml | Hatchling, LiteLLM >=1.80.7,<2, Pixi tasks | Replace | Independently authored minimal Python package | Build not executed upstream | pyproject.toml |

README and docs/usage.md describe OAuth access, models and tools. These are documented
claims, not proof of complete behavior. RPC transport, initialization, event correlation,
interrupts, concurrency, reconnection, session isolation and safe approval rejection all
require new implementation. Stateful sessions and dynamic tools remain later work.
