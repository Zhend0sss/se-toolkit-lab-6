from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _FakeLLMHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)

        body = {
            "choices": [
                {
                    "message": {
                        "content": "Representational State Transfer.",
                    }
                }
            ]
        }
        payload = json.dumps(body).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def test_agent_outputs_required_json_fields() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    server = HTTPServer(("127.0.0.1", 0), _FakeLLMHandler)
    host, port = server.server_address

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        env = os.environ.copy()
        env["LLM_API_KEY"] = "dummy-key"
        env["LLM_API_BASE"] = f"http://{host}:{port}"
        env["LLM_MODEL"] = "dummy-model"

        cmd = [sys.executable, "agent.py", "What does REST stand for?"]
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip())

    assert "answer" in parsed
    assert isinstance(parsed["answer"], str)
    assert "tool_calls" in parsed
    assert parsed["tool_calls"] == []
