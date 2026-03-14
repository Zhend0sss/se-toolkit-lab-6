# Agent Architecture (Task 3)

## Goal

`agent.py` is now a system agent, not only a docs assistant. It can answer questions from repository documentation, source code, and live backend API data. The architecture still uses a function-calling loop, but Task 3 adds backend access through `query_api` and updates prompt guidance so the model chooses between docs lookup, code inspection, and runtime API queries.

## CLI contract and output

- Input: first CLI argument as the question.
- Output: one JSON object on stdout with:
  - `answer` (string)
  - `source` (string; may be empty for pure API answers)
  - `tool_calls` (array of `{tool, args, result}` records)

Stderr is reserved for errors so stdout stays machine-readable for tests and evaluator scripts.

## Registered tools

The chat request includes three function tools:

- `read_file(path)`: reads a repository file.
- `list_files(path)`: lists files/directories for discovery.
- `query_api(method, path, body?)`: sends an authenticated HTTP request to the backend and returns a JSON string with `status_code` and `body`.

For `query_api`, request auth uses `Authorization: Bearer <LMS_API_KEY>`. The base URL is read from `AGENT_API_BASE_URL` with default `http://localhost:42002`.

## Security and robustness

File tools keep path traversal protections from Task 2:

- absolute paths are rejected,
- paths are resolved against repo root,
- escaping repo root is blocked.

`query_api` validates required args, requires a leading slash in API path, parses optional JSON `body`, and catches network exceptions as tool error strings instead of crashing the agent.

## Environment configuration

All runtime settings come from environment variables (autochecker-safe):

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`
- `LMS_API_KEY`
- `AGENT_API_BASE_URL` (optional default)

Local convenience loading reads `.env.agent.secret` and `.env.docker.secret` using `setdefault` so externally injected values still win.

## Tool-routing strategy

The prompt now explicitly separates question classes:

- Wiki and conceptual questions: `list_files` + `read_file` in `wiki/`.
- Implementation/bug diagnosis: `read_file` over source code.
- Live data questions (counts/scores/status from API responses): `query_api`.

The loop includes two guardrails:

- force at least one tool call before accepting a final answer,
- request a JSON reformat pass if `answer`/`source` is missing.

If the model still omits `source`, the agent falls back to the latest `read_file` path so evaluator source checks have a concrete reference.

## Regression testing added for Task 3

Two unit regression tests were added in `backend/tests/unit/test_agent_task3.py`:

- framework question asserts `read_file` appears in `tool_calls`;
- item-count question runs against a fake authenticated API server and asserts `query_api` was used with a 200 result payload.

These tests run `agent.py` as a subprocess and validate JSON output structure plus tool usage behavior.

## Benchmark notes and lessons

Initial observed local benchmark result was 0/10 (runner stops at first failure), with first failure on missing/invalid source formatting for the branch-protection wiki question. Iterations focused on prompt specificity, JSON formatting retries, and source fallback behavior. The key lesson is that evaluator success depends not only on correctness of content, but also stable output schema and explicit tool-selection behavior under imperfect LLM formatting.
