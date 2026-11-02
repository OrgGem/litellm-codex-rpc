import uuid

from litellm import Choices, Message, ModelResponse
from litellm.types.utils import Usage


def usage_from_rpc(usage):
    if not usage:
        return None
    return Usage(
        prompt_tokens=usage["inputTokens"],
        completion_tokens=usage["outputTokens"],
        total_tokens=usage["totalTokens"],
    )


def response(model, event):
    r = ModelResponse(
        id="chatcmpl-" + uuid.uuid4().hex,
        model=model,
        choices=[
            Choices(
                index=0,
                finish_reason="stop",
                message=Message(role="assistant", content=event.text),
            )
        ],
    )
    # LiteLLM creates zero usage by default. Remove it when backend usage is unknown.
    if event.usage:
        r.usage = usage_from_rpc(event.usage)
    elif hasattr(r, "usage"):
        delattr(r, "usage")
    return r


def chunk(event):
    result = {
        "text": event.text,
        "is_finished": event.done,
        "finish_reason": "stop" if event.done else None,
        "index": 0,
        "tool_use": None,
        "usage": None,
    }
    if event.usage:
        result["usage"] = usage_from_rpc(event.usage).model_dump()
    return result
