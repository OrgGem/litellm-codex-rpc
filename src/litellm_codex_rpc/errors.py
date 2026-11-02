from litellm import APIError


class ProviderError(APIError):
    """Safe public error: never interpolate remote messages or local paths."""

    def __init__(self, category, message, status_code=503):
        self.category = category
        super().__init__(
            status_code=status_code,
            message=f"{category}: {message}",
            llm_provider="codex_rpc",
            model="codex",
        )


def invalid(message):
    return ProviderError("invalid_request", message, 400)


def remote_error(data, code=None):
    if code == -32602:
        return invalid("Codex rejected the model or RPC parameters.")
    info = data.get("codexErrorInfo") if isinstance(data, dict) else None
    if info == "unauthorized":
        return ProviderError(
            "authentication", "Authenticate the external Codex server.", 401
        )
    if info in ("rateLimitExceeded", "usageLimitExceeded", "sessionBudgetExceeded"):
        return ProviderError("rate_limit", "Codex usage limit reached.", 429)
    return ProviderError(
        "protocol", "Codex rejected the operation; inspect server logs."
    )
