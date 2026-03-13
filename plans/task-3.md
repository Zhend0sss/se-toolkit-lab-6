# Task 3 Plan: The System Agent

## Goal

Extend `agent.py` from documentation-only lookup to a system-aware agent that can query the deployed backend API in addition to reading repository files.

Target output remains one JSON object on stdout with:

- `answer` (string)
- `source` (string, optional/possibly empty for pure API answers)
- `tool_calls` (array of executed tools with args and results)

## Tooling update

Add a third function-calling tool schema:

1. `query_api`
   - Parameters:
     - `method` (string; HTTP method like GET/POST)
     - `path` (string; API path beginning with `/`, e.g. `/items/`)
     - `body` (string, optional; JSON request body)
   - Returns: JSON string with fields:
     - `status_code` (number)
     - `body` (parsed JSON value or text)

Existing tools remain unchanged:

- `read_file(path)`
- `list_files(path)`

## Authentication and configuration

Read all config from environment variables (no hardcoded credentials):

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`
- `LMS_API_KEY`
- `AGENT_API_BASE_URL` (default: `http://localhost:42002`)

Implementation details:

- Load local helper files `.env.agent.secret` and `.env.docker.secret` with `setdefault`, so externally injected env vars override local values.
- For `query_api`, send header `Authorization: Bearer <LMS_API_KEY>`.
- Resolve request URL as `<AGENT_API_BASE_URL>/<path-without-leading-slash>`.
- Validate path format (`/`-prefixed) and return tool-level error text on invalid input.

## System prompt update

Update the system prompt to route tool choice:

- Use `list_files` + `read_file` for wiki/documentation answers.
- Use `query_api` for live data or runtime facts (counts, scores, current API responses).
- Use `read_file` on source code for implementation-level facts or diagnosing API errors.
- Return only JSON string with keys `answer` and `source`; allow empty `source` when no single doc/code source applies.

## Agent loop and robustness

- Keep existing loop structure and max-tool-call guard.
- Preserve handling for assistant messages where `content` is null during tool calls.
- Parse `body` argument defensively:
  - if valid JSON object/array, send as JSON payload;
  - if invalid JSON, return a clear tool error string.
- Include each tool invocation in `tool_calls` trace for evaluation checks.

## Testing strategy

Add 2 regression tests that run `agent.py` as a subprocess with a fake LLM server:

1. Static system fact question (framework)
   - Scripted first response asks for `read_file`.
   - Assert `read_file` appears in `tool_calls`.

2. Data-dependent question (item count)
   - Run fake backend API server requiring bearer auth and returning an items list.
   - Scripted first response asks for `query_api`.
   - Assert `query_api` appears in `tool_calls` and result includes status code 200.

## Benchmark diagnosis and iteration strategy

Initial benchmark run:

- Score: 0/10 in the first observed run (the benchmark stops at the first failing question).
- First failure: question index 0 (branch protection question from wiki) failed due missing/invalid `source` output formatting.

Iteration strategy:

1. Run `uv run run_eval.py`.
2. For first failing question, inspect:
   - answer mismatch,
   - expected source mismatch,
   - missing required tool usage.
3. Patch only the smallest relevant area (tool schema description, prompt guidance, or tool implementation).
4. Re-run benchmark and repeat until all 10 local questions pass.
5. Record final score in `AGENT.md` with concrete lessons.

Observed implementation adjustments after first failure:

- Strengthened prompt constraints so the model must use tools before final answer.
- Added a formatting retry if the assistant returns non-JSON or omits `source`.
- Added fallback source inference from the latest `read_file` call when the model omits source.
