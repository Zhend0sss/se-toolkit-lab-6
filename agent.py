from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def ask_llm(question: str, api_key: str, api_base: str, model: str) -> str:
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Invalid LLM response format: missing message content") from exc

    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"<question>\"", file=sys.stderr)
        return 2

    load_env_file(Path(".env.agent.secret"))

    question = sys.argv[1]

    try:
        api_key = require_env("LLM_API_KEY")
        api_base = require_env("LLM_API_BASE")
        model = require_env("LLM_MODEL")
        answer = ask_llm(question=question, api_key=api_key, api_base=api_base, model=model)
    except Exception as exc:  # noqa: BLE001
        print(f"agent.py error: {exc}", file=sys.stderr)
        return 1

    output = {"answer": answer, "tool_calls": []}
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())