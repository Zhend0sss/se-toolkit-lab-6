# Agent Architecture (Task 2)

## Goal

`agent.py` is a CLI documentation agent that uses an LLM with function calling to answer questions from repository docs. It can inspect files through tools and run an agentic loop until it has enough context.

## Inputs and outputs

- Input: first CLI argument.
  - Example: `uv run agent.py "What does REST stand for?"`
- Output: a single JSON line to stdout with required fields:
  - `answer`: final response text
  - `source`: wiki source reference (`path#anchor`)
  - `tool_calls`: array of executed tool invocations with `tool`, `args`, `result`

All logs and errors are written to stderr so stdout remains valid machine-readable JSON.

## Tools

The agent registers two function-calling tools in every chat-completions request:

- `read_file(path)`
  - Reads a repository file and returns its text.
  - Used when the model needs details from wiki pages or source files.

- `list_files(path)`
  - Lists files/directories under a repository directory.
  - Used for discovery before selecting a concrete file to read.

### Tool security

Tool paths are validated to stay inside repository root:

- Absolute paths are rejected.
- Traversal outside root (e.g., `../`) is rejected after `resolve()`.
- Errors are returned as tool result text instead of crashing.

## Configuration

The agent reads configuration from environment variables:

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`

For local development convenience, `agent.py` also reads `.env.agent.secret` and sets values only if they are not already present in the process environment.

## Agentic loop flow

1. Parse question from CLI args.
2. Load environment variables.
3. Build initial messages (`system` + `user`) and include tool schemas.
4. Send request to `${LLM_API_BASE}/chat/completions`.
5. If model returns `tool_calls`, execute each tool call locally, append tool results as `tool` messages, and continue looping.
6. If model returns final text without `tool_calls`, parse `answer` and `source`.
7. Stop if total tool calls reaches 10.
8. Print JSON result and exit with status code 0.

## System prompt strategy

The system prompt instructs the model to:

- discover relevant docs with `list_files`,
- inspect content with `read_file`,
- and return only a JSON object string containing `answer` and `source`.

The code still handles non-JSON responses safely by falling back to raw text as the answer.

## Error handling

- Missing required environment variables: exit non-zero with stderr message.
- HTTP failures or malformed provider responses: exit non-zero with stderr message.
- Timeout is enforced at the HTTP client level (60 seconds).
- Invalid tool arguments are handled gracefully and returned as tool error strings.

## Provider choice

The agent uses an OpenAI-compatible provider configured through `.env.agent.secret` and environment variables. Qwen Code API is the intended provider for local development.
