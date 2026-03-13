# Task 2 Plan: The Documentation Agent

## Goal

Upgrade `agent.py` from a single LLM call to an agentic loop that can call tools for documentation lookup and return structured output:

- `answer` (string)
- `source` (string)
- `tool_calls` (array of executed calls)

## Tool schemas

Define two OpenAI-compatible function tools in the chat request:

1. `read_file`
   - Input: `{ "path": "relative/path" }`
   - Output: file content string or error string.

2. `list_files`
   - Input: `{ "path": "relative/dir" }`
   - Output: newline-separated directory entries or error string.

## Path security

- Treat all tool paths as relative to project root.
- Reject absolute paths.
- Resolve path via `Path.resolve()` and ensure it remains inside project root.
- Return error text for traversal attempts or invalid targets.

## Agentic loop design

1. Build `messages` with system prompt and user question.
2. Send request with tools.
3. If assistant returns tool calls:
   - Parse tool arguments.
   - Execute each tool.
   - Append tool results as `tool` role messages.
   - Record each call in output trace (`tool`, `args`, `result`).
4. If assistant returns final text with no tool calls:
   - Parse into `answer` and `source`.
5. Stop if total tool calls reaches 10.

## Output strategy

- Instruct model to return final answer as JSON string with `answer` and `source`.
- Parse robustly:
  - JSON object with both fields -> use directly.
  - Otherwise fallback to raw text as `answer` and empty `source`.

## Testing strategy

Add 2 regression tests with a local fake chat-completions server:

1. Merge conflict question:
   - Fake server first requests `read_file`.
   - Final response includes source in `wiki/git-workflow.md#...`.
   - Assert `read_file` appears in `tool_calls` and source path is correct.

2. Wiki listing question:
   - Fake server first requests `list_files` for `wiki`.
   - Assert `list_files` appears in `tool_calls`.

Both tests run `agent.py` as a subprocess and validate stdout JSON structure.
