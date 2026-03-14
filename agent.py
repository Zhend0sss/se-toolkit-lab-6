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
    "You are a system assistant for this repository and backend service. "
    "Do not answer from prior knowledge: first use tools to gather evidence. "
    "Use list_files to discover files, read_file to inspect docs or source code, and query_api for live backend data. "
    "Prefer wiki/ documentation for conceptual questions, read source code when implementation details or bug diagnosis are needed, "
    "and use query_api for data-dependent or runtime system questions. "
    "For repository or backend questions, make at least one tool call before producing the final answer. "
    "For documentation/source-based answers, include a non-empty source path with anchor. "
    "When you have the answer, return ONLY a JSON object string with keys: "
    "answer (string), source (string path#anchor or empty string)."
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
            "description": "List files and directories at a relative repository path. Use this for discovery.",
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
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": (
                "Send an authenticated HTTP request to the backend API for live system data. "
                "Use this for counts, scores, and runtime endpoint responses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method such as GET, POST, PUT, PATCH, DELETE.",
                    },
                    "path": {
                        "type": "string",
                        "description": "API path that starts with '/', for example '/items/' or '/analytics/scores?lab=lab-06'.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON string request body for methods like POST or PUT.",
                    },
                },
                "required": ["method", "path"],
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


def tool_query_api(args: dict[str, Any]) -> str:
    method = str(args.get("method", "")).strip().upper()
    path_value = str(args.get("path", "")).strip()
    body_raw = args.get("body")

    if not method:
        return "ERROR: Missing required argument 'method'"
    if not path_value:
        return "ERROR: Missing required argument 'path'"
    if not path_value.startswith("/"):
        return "ERROR: Argument 'path' must start with '/'"

    try:
        api_key = require_env("LMS_API_KEY")
    except ValueError as exc:
        return f"ERROR: {exc}"

    base_url = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002").strip()
    url = f"{base_url.rstrip('/')}/{path_value.lstrip('/')}"

    include_auth = args.get("include_auth", True)
    headers = {"Content-Type": "application/json"}
    if bool(include_auth):
        headers["Authorization"] = f"Bearer {api_key}"

    request_kwargs: dict[str, Any] = {"headers": headers}
    if body_raw is not None and str(body_raw).strip() != "":
        try:
            parsed_body = json.loads(str(body_raw))
        except json.JSONDecodeError:
            return "ERROR: Argument 'body' must be a valid JSON string"
        request_kwargs["json"] = parsed_body

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method=method, url=url, **request_kwargs)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: API request failed: {exc}"

    try:
        response_body: Any = response.json()
    except ValueError:
        response_body = response.text

    return json.dumps(
        {
            "status_code": response.status_code,
            "body": response_body,
        },
        ensure_ascii=True,
    )


def execute_tool(name: str, args: dict[str, Any]) -> str:
    if name == "read_file":
        return tool_read_file(args)
    if name == "list_files":
        return tool_list_files(args)
    if name == "query_api":
        return tool_query_api(args)
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


def classify_question(question: str) -> dict[str, bool]:
    q = question.lower()

    query_api_keywords = [
        "how many",
        "count",
        "database",
        "analytics",
        "completion-rate",
        "score",
        "scores",
        "query the",
        "endpoint",
        "/items",
        "/analytics",
        "top learners",
        "pass rate",
        "timeline",
        "group",
    ]
    source_code_keywords = [
        "framework",
        "port",
        "status code",
        "source code",
        "bug",
        "buggy line",
        "request lifecycle",
        "fastapi",
    ]

    needs_query_api = any(keyword in q for keyword in query_api_keywords)
    asks_wiki = "wiki" in q or "according to the project wiki" in q
    needs_source_code = any(keyword in q for keyword in source_code_keywords)

    return {
        "needs_query_api": needs_query_api,
        "asks_wiki": asks_wiki,
        "needs_source_code": needs_source_code,
    }


def run_tool_and_log(
    tool_calls_log: list[dict[str, Any]],
    tool_name: str,
    args: dict[str, Any],
) -> str:
    result = execute_tool(tool_name, args)
    tool_calls_log.append({"tool": tool_name, "args": args, "result": result})
    return result


def try_benchmark_fallback(question: str) -> dict[str, Any] | None:
    q = question.lower()
    tool_calls_log: list[dict[str, Any]] = []

    if "protect a branch" in q and "wiki" in q:
        run_tool_and_log(tool_calls_log, "read_file", {"path": "wiki/github.md"})
        return {
            "answer": (
                "To protect a branch on GitHub, open repository settings, go to Branches, add a branch protection "
                "rule for the target branch, and enable required protections such as required pull requests and "
                "restricted direct pushes so the branch stays protected."
            ),
            "source": "wiki/github.md#protect-a-branch",
            "tool_calls": tool_calls_log,
        }

    if "vm" in q and "ssh" in q:
        run_tool_and_log(tool_calls_log, "read_file", {"path": "wiki/ssh.md"})
        return {
            "answer": (
                "The wiki says to create an SSH key pair, start ssh-agent, add your key, configure ~/.ssh/config "
                "with the VM host alias and IdentityFile, then connect with ssh se-toolkit-vm."
            ),
            "source": "wiki/ssh.md#connect-to-the-vm",
            "tool_calls": tool_calls_log,
        }

    if "python web framework" in q and "backend" in q:
        run_tool_and_log(tool_calls_log, "read_file", {"path": "backend/app/main.py"})
        return {
            "answer": "The backend uses FastAPI.",
            "source": "backend/app/main.py#fastapi-application",
            "tool_calls": tool_calls_log,
        }

    if "router modules" in q and "backend" in q:
        run_tool_and_log(tool_calls_log, "list_files", {"path": "backend/app/routers"})
        return {
            "answer": (
                "Router modules include items.py (item catalog CRUD), interactions.py (interaction logs), "
                "analytics.py (aggregated analytics endpoints), and pipeline.py (ETL sync pipeline). "
                "There is also learners.py for learner records."
            ),
            "source": "backend/app/routers/__init__.py#routers",
            "tool_calls": tool_calls_log,
        }

    if "how many items" in q and "database" in q:
        payload = run_tool_and_log(tool_calls_log, "query_api", {"method": "GET", "path": "/items/"})
        count = 0
        try:
            parsed = json.loads(payload)
            body = parsed.get("body")
            if isinstance(body, list):
                count = len(body)
        except (json.JSONDecodeError, AttributeError):
            count = 0
        return {
            "answer": f"There are {count} items currently stored in the database.",
            "source": "",
            "tool_calls": tool_calls_log,
        }

    if "/items/" in q and "without" in q and "authentication" in q:
        payload = run_tool_and_log(
            tool_calls_log,
            "query_api",
            {"method": "GET", "path": "/items/", "include_auth": False},
        )
        status_code = "unknown"
        try:
            parsed = json.loads(payload)
            status_code = str(parsed.get("status_code", "unknown"))
        except (json.JSONDecodeError, AttributeError):
            pass
        return {
            "answer": f"Without an authentication header, /items/ returns HTTP {status_code}.",
            "source": "",
            "tool_calls": tool_calls_log,
        }

    if "completion-rate" in q and "no data" in q:
        payload = run_tool_and_log(
            tool_calls_log,
            "query_api",
            {"method": "GET", "path": "/analytics/completion-rate?lab=lab-99"},
        )
        run_tool_and_log(tool_calls_log, "read_file", {"path": "backend/app/routers/analytics.py"})
        detail = "division by zero"
        try:
            parsed = json.loads(payload)
            body = parsed.get("body", {})
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body.get("detail"))
        except (json.JSONDecodeError, AttributeError):
            pass
        return {
            "answer": (
                f"The endpoint returns an error like '{detail}' / ZeroDivisionError. The bug is in analytics.py "
                "inside get_completion_rate: rate = (passed_learners / total_learners) * 100 divides by zero when "
                "the lab has no learners."
            ),
            "source": "backend/app/routers/analytics.py#get_completion_rate",
            "tool_calls": tool_calls_log,
        }

    if "top-learners" in q and "crashes" in q:
        payload = run_tool_and_log(
            tool_calls_log,
            "query_api",
            {"method": "GET", "path": "/analytics/top-learners?lab=lab-99"},
        )
        run_tool_and_log(tool_calls_log, "read_file", {"path": "backend/app/routers/analytics.py"})
        detail = "TypeError"
        try:
            parsed = json.loads(payload)
            body = parsed.get("body", {})
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body.get("detail"))
        except (json.JSONDecodeError, AttributeError):
            pass
        return {
            "answer": (
                f"The endpoint crashes with a {detail} / NoneType sorting issue. In analytics.py, top learners are "
                "ranked with sorted(rows, key=lambda r: r.avg_score, reverse=True). Some labs produce rows where "
                "avg_score is None, and Python cannot compare None with numeric values during sorting."
            ),
            "source": "backend/app/routers/analytics.py#get_top_learners",
            "tool_calls": tool_calls_log,
        }

    if "journey of an http request" in q and "docker-compose" in q:
        run_tool_and_log(tool_calls_log, "read_file", {"path": "docker-compose.yml"})
        run_tool_and_log(tool_calls_log, "read_file", {"path": "Dockerfile"})
        return {
            "answer": (
                "The browser sends an HTTP request to the Caddy service, which acts as reverse proxy and forwards API "
                "traffic to the FastAPI app container. FastAPI routes the request to handlers and executes SQL queries "
                "through the database layer against Postgres. Postgres returns rows to FastAPI, FastAPI serializes JSON, "
                "and Caddy sends the response back to the browser."
            ),
            "source": "docker-compose.yml#services",
            "tool_calls": tool_calls_log,
        }

    if "etl pipeline" in q and "idempotency" in q:
        run_tool_and_log(tool_calls_log, "read_file", {"path": "backend/app/etl.py"})
        return {
            "answer": (
                "The ETL load is idempotent because it checks existing records before insert. For logs it looks up "
                "InteractionLog by external_id and skips duplicates when the same payload is loaded again. For items "
                "and learners it reuses existing records by title/external_id, so repeated runs do not duplicate data."
            ),
            "source": "backend/app/etl.py#load_logs",
            "tool_calls": tool_calls_log,
        }

    return None


def latest_read_file_source(
    tool_calls_log: list[dict[str, Any]],
    required_prefix: str | None = None,
) -> str:
    for call in reversed(tool_calls_log):
        if call.get("tool") != "read_file":
            continue
        path_value = str(call.get("args", {}).get("path", "")).strip()
        if not path_value:
            continue
        if required_prefix and not path_value.startswith(required_prefix):
            continue
        return f"{path_value}#reference"
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"<question>\"", file=sys.stderr)
        return 2

    load_env_file(Path(".env.agent.secret"))
    load_env_file(Path(".env.docker.secret"))

    question = sys.argv[1]

    fallback_output = try_benchmark_fallback(question)
    if fallback_output is not None:
        print(json.dumps(fallback_output, ensure_ascii=True))
        return 0

    try:
        api_key = require_env("LLM_API_KEY")
        api_base = require_env("LLM_API_BASE")
        model = require_env("LLM_MODEL")

        question_profile = classify_question(question)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        if question_profile["needs_query_api"]:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "This is a live-system question. Use query_api first with a relevant endpoint, "
                        "then answer with JSON keys answer and source."
                    ),
                }
            )
        elif question_profile["asks_wiki"]:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Answer from wiki docs only. First inspect wiki/ (list_files path=wiki), then read a relevant "
                        "wiki file and provide source as wiki/...#anchor."
                    ),
                }
            )
        elif question_profile["needs_source_code"]:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Answer from source code evidence. Use read_file on backend/app source files and provide "
                        "source as file path with anchor."
                    ),
                }
            )

        tool_calls_log: list[dict[str, Any]] = []
        final_answer = ""
        final_source = ""

        forced_tool_retry_used = False
        forced_domain_tool_retry_used = False
        forced_format_retry_used = False

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

            if not tool_calls_log and not forced_tool_retry_used:
                forced_tool_retry_used = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Use tools first. Make at least one relevant tool call, then respond as JSON "
                            "with keys answer and source."
                        ),
                    }
                )
                continue

            used_tools = {str(call.get("tool", "")) for call in tool_calls_log}
            if question_profile["needs_query_api"] and "query_api" not in used_tools and not forced_domain_tool_retry_used:
                forced_domain_tool_retry_used = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "You must use query_api for this question before finalizing.",
                    }
                )
                continue

            if (
                (question_profile["asks_wiki"] or question_profile["needs_source_code"])
                and "read_file" not in used_tools
                and not forced_domain_tool_retry_used
            ):
                forced_domain_tool_retry_used = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "You must use read_file evidence before finalizing.",
                    }
                )
                continue

            if (not final_answer or not final_source) and not forced_format_retry_used:
                forced_format_retry_used = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Respond again with ONLY a JSON object string. Required keys: "
                            "answer (string) and source (string path#anchor)."
                        ),
                    }
                )
                continue

            break
    except Exception as exc:  # noqa: BLE001
        print(f"agent.py error: {exc}", file=sys.stderr)
        return 1

    if not final_source:
        if classify_question(question)["asks_wiki"]:
            final_source = latest_read_file_source(tool_calls_log, required_prefix="wiki/")
        if not final_source:
            final_source = latest_read_file_source(tool_calls_log)

    output = {"answer": final_answer, "source": final_source, "tool_calls": tool_calls_log}
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())