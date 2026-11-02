# Implementation baseline — 0.2.0 draft

Source: the user's LiteLLM Codex RPC Provider Business Requirements Document & Technical
Implementation Plan, version 0.2.0. This file records scope and traceability, not a replacement
for that specification.

Goal: an installable LiteLLM CustomLLM plugin using an external authenticated Codex App Server,
without reading OAuth credentials or introducing an HTTP adapter. Priorities are licensing,
protocol correctness, isolation, incremental output and explicit unsupported errors.

MVP: stateless text completions over Unix WebSocket/TCP WebSocket, optional stdio, request
correlation, concurrency of five, timeouts, interrupts, safe errors, configurable aliases and
Proxy integration. Prompt flattening requires opt-in; tool calls, multimodal input and exact
history role semantics are unsupported. Reference implementation reuse is gated on licensing.

Phases 0–3 are partially implemented and locally tested. The live completion exit criterion
is still unmet. Stateful sessions, client-owned dynamic tools, advanced model/usage discovery,
Responses API and agent mode are deferred. docs/COMPATIBILITY.md records actual evidence;
unchecked live requirements must not be described as delivered acceptance criteria.
