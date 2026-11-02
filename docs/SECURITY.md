# Security and authorization

Use only a personal or explicitly authorized self-hosted account. Technical interoperability
with Codex does not grant permission to redistribute subscription resources or operate a
commercial inference API. Respect OpenAI policies and account limits. This project provides
no subscription pooling or limit bypass.

RPC code never reads auth.json, extracts OAuth tokens or refreshes credentials. Codex alone
owns that lifecycle. Remote WebSocket access tokens are distinct from Codex OAuth credentials.
Use a dedicated Codex service with no unrelated MCP servers, plugins, hooks, skills or secrets,
and an empty working directory. Apply OS/container filesystem and network restrictions to
that service. Do not share the interactive developer's Codex server with untrusted clients.

Read-only sandbox, disabled shell/unified execution feature flags and rejected approval requests
reduce execution privileges. They are not a universal guarantee that every Codex tool is disabled.
Read-only commands may otherwise run without approval, and detecting an item/started event is
too late to prevent execution. Agent mode is therefore unavailable; do not expose this experimental
provider to untrusted prompts without external runtime confinement. Dedicated tool-free model
execution needs further live validation before a production security claim.

Restrict Unix socket and parent directory ownership; world-accessible sockets are rejected.
Never publish a Codex listener to the Internet. Remote deployments require TLS, server capability
authentication, and a trusted private network. Configure LiteLLM master-key authentication.
The Compose example binds only loopback and mounts only the socket directory, never auth state.
Keep socket group permission aligned with the nonroot proxy UID. A read-only bind mount does not
make RPC read-only: access to the socket confers the server's protocol privileges.

Safe errors omit remote text and local paths. Protect LiteLLM/Codex logs independently; upstream
software can log conversation content. Shutdown hooks should call provider.aclose(). Multiworker
processes must instantiate after fork and enforce aggregate limits outside this package.
