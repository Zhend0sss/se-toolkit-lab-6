# Task 1 Plan: Call an LLM from Code

## Provider and model

- Provider type: OpenAI-compatible chat completions API.
- Intended provider for local usage: Qwen Code API.
- Model: from `LLM_MODEL` environment variable (default expected in local env file).

## CLI behavior

- Input: first command-line argument is the user question.
- Output: one JSON object to stdout with required fields:
  - `answer` (string)
  - `tool_calls` (array, empty for Task 1)
- All debug and error details go to stderr.

## Data flow

1. Read question from CLI args.
2. Load environment from process and optionally `.env.agent.secret`.
3. Validate `LLM_API_KEY`, `LLM_API_BASE`, and `LLM_MODEL`.
4. Send chat completion request with system + user message.
5. Parse `choices[0].message.content` as the answer.
6. Print JSON line to stdout and exit 0.

## Error handling

- Missing args or missing env vars: print clear error to stderr, exit non-zero.
- HTTP/network errors and invalid provider responses: print to stderr, exit non-zero.
- Timeout: 60 seconds max for the LLM call.

## Testing approach

- Add one regression test that runs `agent.py` as a subprocess.
- Use a local fake HTTP server that mimics `/chat/completions` so the test is deterministic.
- Assert stdout is valid JSON and includes `answer` + `tool_calls`.