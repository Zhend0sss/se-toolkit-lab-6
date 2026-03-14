from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


class _Task2FakeLLMHandler(BaseHTTPRequestHandler):
    responses_by_question: dict[str, list[dict[str, Any]]] = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        request_data = json.loads(raw.decode("utf-8"))

        messages = request_data.get("messages", [])
        question = ""
        for message in messages:
            if message.get("role") == "user":
                question = str(message.get("content", ""))
                break

        queue = self.responses_by_question.get(question)
        if not queue:
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "No scripted response.",
                                    "source": "",
                                }
                            )
                        }
                    }
                ]
            }
        else:
            body = {"choices": [{"message": queue.pop(0)}]}

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _run_agent_with_scripted_responses(
    question: str,
    scripted_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    _Task2FakeLLMHandler.responses_by_question = {question: scripted_messages.copy()}

    server = HTTPServer(("127.0.0.1", 0), _Task2FakeLLMHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env = os.environ.copy()
        env["LLM_API_KEY"] = "dummy-key"
        env["LLM_API_BASE"] = f"http://{host}:{port}"
        env["LLM_MODEL"] = "dummy-model"

        result = subprocess.run(
            [sys.executable, "agent.py", question],
            cwd=repo_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=25,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_task2_merge_conflict_uses_read_file_and_sets_source() -> None:
    question = "How do you resolve a merge conflict?"
    scripted_messages = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "wiki/git-workflow.md"}),
                    },
                }
            ],
        },
        {
            "content": json.dumps(
                {
                    "answer": "Resolve conflicts by editing files, staging them, and committing.",
                    "source": "wiki/git-workflow.md#resolving-merge-conflicts",
                }
            )
        },
    ]

    output = _run_agent_with_scripted_responses(question, scripted_messages)

    assert output["source"].startswith("wiki/git-workflow.md")
    assert any(call["tool"] == "read_file" for call in output["tool_calls"])


def test_task2_wiki_listing_uses_list_files() -> None:
    question = "What files are in the wiki?"
    scripted_messages = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "arguments": json.dumps({"path": "wiki"}),
                    },
                }
            ],
        },
        {
            "content": json.dumps(
                {
                    "answer": "The wiki includes many markdown files like git-workflow.md and api.md.",
                    "source": "wiki/git-workflow.md#git-workflow",
                }
            )
        },
    ]

    output = _run_agent_with_scripted_responses(question, scripted_messages)

    assert any(call["tool"] == "list_files" for call in output["tool_calls"])