import json

from ..errors import invalid


def convert(messages, flatten=False):
    if not isinstance(messages, list) or not messages:
        raise invalid("messages must be a nonempty list.")
    for m in messages:
        if not isinstance(m, dict) or set(m) - {"role", "content"}:
            raise invalid("Only role and text content are supported.")
        if m.get("role") not in {
            "user",
            "assistant",
            "system",
            "developer",
        } or not isinstance(m.get("content"), str):
            raise invalid(
                "Only text user, assistant, system and developer messages are supported."
            )
    if len(messages) == 1 and messages[0]["role"] == "user":
        return messages[0]["content"]
    if not flatten:
        raise invalid(
            "History and instruction roles require explicit CODEX_RPC_ALLOW_PROMPT_FLATTENING=true; exact role semantics are unavailable."
        )
    return (
        "Conversation context as ordered JSON messages (roles are descriptive, not protocol roles):\n"
        + json.dumps(messages, ensure_ascii=False)
    )
