"""Validate this implementation's request shapes against installed Codex schemas."""

import json
import subprocess
import tempfile
from pathlib import Path

import jsonschema

with tempfile.TemporaryDirectory() as directory:
    subprocess.run(
        ["codex", "app-server", "generate-json-schema", "--out", directory], check=True
    )
    examples = {
        "InitializeParams": {
            "clientInfo": {"name": "litellm_codex_rpc", "version": "0.2.0"}
        },
        "ThreadStartParams": {
            "model": None,
            "ephemeral": True,
            "approvalPolicy": "untrusted",
            "sandbox": "read-only",
            "config": {
                "features.shell_tool": False,
                "features.unified_exec": False,
                "features.apply_patch_freeform": False,
                "web_search": "disabled",
            },
        },
        "TurnStartParams": {
            "threadId": "schema-example",
            "input": [{"type": "text", "text": "hello"}],
        },
        "TurnInterruptParams": {"threadId": "schema-example", "turnId": "schema-turn"},
        "GetAccountParams": {"refreshToken": False},
    }
    for name, value in examples.items():
        matches = list(Path(directory).rglob(name + ".json"))
        if len(matches) != 1:
            raise RuntimeError("Missing or ambiguous schema: " + name)
        jsonschema.validate(value, json.loads(matches[0].read_text()))
        print(name, "PASS")
