# Agent Architecture (Task 1)

## Goal

`agent.py` is a minimal CLI agent that sends a user question to an LLM using the OpenAI-compatible Chat Completions API and returns structured JSON.

## Inputs and outputs

- Input: first CLI argument.
  - Example: `uv run agent.py "What does REST stand for?"`
- Output: a single JSON line to stdout with required fields:
  - `answer`: model response text
  - `tool_calls`: empty array in Task 1

All logs and errors are written to stderr so stdout remains valid machine-readable JSON.

## Configuration

The agent reads configuration from environment variables:

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`

For local development convenience, `agent.py` also reads `.env.agent.secret` and sets values only if they are not already present in the process environment.

## Request flow

1. Parse question from CLI args.
2. Load environment variables.
3. Build a chat completion request (`system` + `user` message).
4. Send HTTP POST to `${LLM_API_BASE}/chat/completions` with a 60-second timeout.
5. Extract `choices[0].message.content` from the response.
6. Print JSON result and exit with status code 0.

## Error handling

- Missing required environment variables: exit non-zero with stderr message.
- HTTP failures or malformed provider responses: exit non-zero with stderr message.
- Timeout is enforced at the HTTP client level (60 seconds).

## Provider choice

Task 1 plan targets an OpenAI-compatible provider and is intended to be used with Qwen Code API by setting values in `.env.agent.secret`.