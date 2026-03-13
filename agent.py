from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parent
MAX_TOOL_CALLS = 10
SYSTEM_PROMPT = (
    "You are a documentation assistant for this repository. "
    "Use list_files to discover wiki files and read_file to inspect relevant content. "
    "Prefer wiki/ documentation first. "
    "When you have the answer, return ONLY a JSON object string with keys: "
    "answer (string), source (string path#anchor)."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from this repository by relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path from repository root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a relative repository path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from repository root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


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


def safe_repo_path(path_value: str) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        raise ValueError("Path must be relative to repository root")

    resolved = (REPO_ROOT / candidate).resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise ValueError("Path traversal outside repository root is not allowed")
    return resolved


def tool_read_file(args: dict[str, Any]) -> str:
    path_value = str(args.get("path", ""))
    if not path_value:
        return "ERROR: Missing required argument 'path'"

    try:
        target = safe_repo_path(path_value)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not target.exists():
        return f"ERROR: File does not exist: {path_value}"
    if not target.is_file():
        return f"ERROR: Path is not a file: {path_value}"

    try:
        return target.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: Failed to read file: {exc}"


def tool_list_files(args: dict[str, Any]) -> str:
    path_value = str(args.get("path", ""))
    if not path_value:
        return "ERROR: Missing required argument 'path'"

    try:
        target = safe_repo_path(path_value)
    except ValueError as exc:
        return f"ERROR: {exc}"

    if not target.exists():
        return f"ERROR: Directory does not exist: {path_value}"
    if not target.is_dir():
        return f"ERROR: Path is not a directory: {path_value}"

    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        entries.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(entries)


def execute_tool(name: str, args: dict[str, Any]) -> str:
    if name == "read_file":
        return tool_read_file(args)
    if name == "list_files":
        return tool_list_files(args)
    return f"ERROR: Unknown tool: {name}"


def chat_completion(
    messages: list[dict[str, Any]],
    api_key: str,
    api_base: str,
    model: str,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
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
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Invalid LLM response format: missing assistant message") from exc
    if not isinstance(message, dict):
        raise ValueError("Invalid LLM response format: assistant message must be an object")
    return message


def parse_final_answer(content: Any) -> tuple[str, str]:
    if isinstance(content, list):
        text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    else:
        text = str(content or "")

    raw = text.strip()
    if not raw:
        return "", ""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw, ""

    if not isinstance(parsed, dict):
        return raw, ""

    answer = str(parsed.get("answer", "")).strip()
    source = str(parsed.get("source", "")).strip()
    if not answer:
        answer = raw
    return answer, source


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

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        tool_calls_log: list[dict[str, Any]] = []
        final_answer = ""
        final_source = ""

        while True:
            message = chat_completion(
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                model=model,
            )
            assistant_content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls") or []

            if raw_tool_calls and len(tool_calls_log) < MAX_TOOL_CALLS:
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "tool_calls": raw_tool_calls,
                    }
                )

                for call in raw_tool_calls:
                    if len(tool_calls_log) >= MAX_TOOL_CALLS:
                        break

                    call_id = str(call.get("id", ""))
                    function_data = call.get("function") or {}
                    tool_name = str(function_data.get("name", ""))
                    arguments_raw = function_data.get("arguments") or "{}"

                    try:
                        parsed_args = json.loads(arguments_raw)
                        if not isinstance(parsed_args, dict):
                            parsed_args = {}
                    except json.JSONDecodeError:
                        parsed_args = {}

                    result = execute_tool(tool_name, parsed_args)
                    tool_calls_log.append(
                        {
                            "tool": tool_name,
                            "args": parsed_args,
                            "result": result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result,
                        }
                    )

                if len(tool_calls_log) >= MAX_TOOL_CALLS:
                    break
                continue

            final_answer, final_source = parse_final_answer(assistant_content)
            break
    except Exception as exc:  # noqa: BLE001
        print(f"agent.py error: {exc}", file=sys.stderr)
        return 1

    output = {"answer": final_answer, "source": final_source, "tool_calls": tool_calls_log}
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())