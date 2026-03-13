from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


class _Task3FakeLLMHandler(BaseHTTPRequestHandler):
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


class _Task3FakeAPIHandler(BaseHTTPRequestHandler):
    expected_key = ""

    def do_GET(self) -> None:  # noqa: N802
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {self.expected_key}":
            payload = json.dumps({"detail": "Invalid API key"}).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/items/":
            payload = json.dumps([
                {"id": 1, "title": "Item A"},
                {"id": 2, "title": "Item B"},
                {"id": 3, "title": "Item C"},
            ]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        payload = json.dumps({"detail": "Not found"}).encode("utf-8")
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _run_agent_with_servers(
    question: str,
    scripted_messages: list[dict[str, Any]],
    lms_api_key: str = "task3-test-key",
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    _Task3FakeLLMHandler.responses_by_question = {question: scripted_messages.copy()}
    _Task3FakeAPIHandler.expected_key = lms_api_key

    llm_server = HTTPServer(("127.0.0.1", 0), _Task3FakeLLMHandler)
    llm_host, llm_port = llm_server.server_address
    llm_thread = threading.Thread(target=llm_server.serve_forever, daemon=True)
    llm_thread.start()

    api_server = HTTPServer(("127.0.0.1", 0), _Task3FakeAPIHandler)
    api_host, api_port = api_server.server_address
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    try:
        env = os.environ.copy()
        env["LLM_API_KEY"] = "dummy-key"
        env["LLM_API_BASE"] = f"http://{llm_host}:{llm_port}"
        env["LLM_MODEL"] = "dummy-model"
        env["LMS_API_KEY"] = lms_api_key
        env["AGENT_API_BASE_URL"] = f"http://{api_host}:{api_port}"

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
        llm_server.shutdown()
        llm_server.server_close()
        llm_thread.join(timeout=2)

        api_server.shutdown()
        api_server.server_close()
        api_thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_task3_framework_question_uses_read_file() -> None:
    question = "What framework does the backend use?"
    scripted_messages = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "backend/app/main.py"}),
                    },
                }
            ],
        },
        {
            "content": json.dumps(
                {
                    "answer": "The backend uses FastAPI.",
                    "source": "backend/app/main.py#application-definition",
                }
            )
        },
    ]

    output = _run_agent_with_servers(question, scripted_messages)

    assert any(call["tool"] == "read_file" for call in output["tool_calls"])


def test_task3_item_count_question_uses_query_api() -> None:
    question = "How many items are in the database?"
    scripted_messages = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "query_api",
                        "arguments": json.dumps({"method": "GET", "path": "/items/"}),
                    },
                }
            ],
        },
        {
            "content": json.dumps(
                {
                    "answer": "There are 3 items in the database.",
                    "source": "",
                }
            )
        },
    ]

    output = _run_agent_with_servers(question, scripted_messages)

    query_calls = [call for call in output["tool_calls"] if call["tool"] == "query_api"]
    assert query_calls, "Expected at least one query_api tool call"

    result_payload = json.loads(query_calls[0]["result"])
    assert result_payload["status_code"] == 200
