# Agent evals: can an agent use the tools correctly from their descriptions?

Unit and framework tests prove the tools behave correctly. They don't prove an
agent will **use** them correctly. An agent knows a tool only through its name,
parameter schema, and description. An agent eval runs a fresh agent, with no
other context, against the server and real tasks, and measures what it did.

Run one when adding or reworking tools whose misuse would damage data (writes,
deletes, position-based edits), when changing a tool's description, and before
releasing a breaking change to a tool surface.

## Principles

1. **Isolate the agent.** It sees only the server under test, started from
   the working tree (not an installed snapshot), and none of the user's other
   MCP servers, connectors, or extensions. Run it from an empty scratch
   directory so no project context file (`CLAUDE.md`, `AGENTS.md`, …) loads.
2. **Allow only the server's tools.** Auto-approve the server's tools and
   deny shell and file-write tools, so the agent can't route around a tool
   (or "fix" the data by hand) and every effect comes through the tool surface.
3. **Give realistic, under-specified prompts.** Phrase tasks the way a user
   would ("change the bullet that says X"), with only the IDs a user would
   paste. Never mention parameters, recipes, or the right tool.
4. **Fresh data per task.** Build a representative fixture (the trickiest
   real-world content the tools must handle) and give each task its own copy,
   so tasks can't interfere and every run starts identical. If the backend
   has a write quota, build the fixture once and copy it per task: a copy is
   usually cheaper than rebuilding.
5. **Record every step.** Use the harness's step-level output (stream JSON) to
   capture each tool call and, where the harness exposes it, each result.
6. **Judge the end state, not the transcript.** Compare the data after the run
   with the data before: everything the task targeted changed as asked, and
   **nothing else changed**. A run that "succeeded" but touched one extra
   field fails.
7. **Measure first-try quality too.** Per task: pass/fail, tool calls, write
   attempts, writes the server refused (and why), and whether the agent got
   stuck. Refusals that a guard caught are good news about the guard and bad
   news about the description: aim for correct-on-first-try.
8. **Iterate on the descriptions, not the agent.** When agents repeat a
   mistake, fix the tool description (or the error message, or the tool's
   design) and rerun the same tasks. Keep the tasks fixed between runs so
   results compare.
9. **Clean up.** Delete or trash every fixture and copy, and remove any
   temporary harness configuration the run created.

## What to look for

- **Escapes in descriptions.** In Python, a `"\n"` inside a normal docstring
  becomes a real line break, so the agent sees a broken example instead of the
  two characters `\n`. Use raw docstrings (`r"""…"""`) for descriptions that
  show escapes, and check the rendered description (`tool.__doc__`) before an
  eval.
- **Rules that fight the underlying API.** If agents keep making the same
  "mistake", check whether they're following the API's real semantics and
  the tool layer invented a different rule. Aligning the tool with the API
  usually beats adding more explanation.
- **Under-specified recipes.** A recipe that shows the request but not the
  matching guard input (expectation, revision, confirmation flag) gets copied
  without it.
- **Silent wrong targets.** Any run where the end-state diff shows a change
  outside the task is the most important finding; fix it before anything else.
- **Deployed surface.** After deploying, confirm the hosted server advertises
  exactly the expected tools (e.g. with the admin CLI's tool listing) before
  pointing agents at it.

## Harness recipes

Each recipe gives the same four things: a server-only MCP config, a tool
allowlist with shell and file writes denied, headless execution, and stream
output. For any other harness, use its headless mode restricted to the server
under test, with step-level output, and apply the same principles.

### Claude Code

Verified with Claude Code 2.1.

`mcp.json` in the scratch directory, pointing at the working tree's
entry point (not the installed binary):

```json
{"mcpServers": {"myapp": {"command": "/path/to/repo/.venv/bin/myapp-mcp",
                          "args": ["stdio", "--user", "local"]}}}
```

```bash
cd "$SCRATCH" && claude -p "<task prompt>" \
  --mcp-config mcp.json --strict-mcp-config \
  --allowedTools mcp__myapp__tool_a mcp__myapp__tool_b \
  --disallowedTools Bash Read Write Edit Glob Grep WebFetch WebSearch Task Agent NotebookEdit \
  --output-format stream-json --verbose --no-session-persistence --max-turns 30 \
  < /dev/null
```

- `--strict-mcp-config` ignores the user's own servers and connectors.
- `--bare` would also skip user context, but it requires API-key auth; with a
  subscription login, run from an empty scratch directory instead (the user's
  global context file still loads; it doesn't mention the server's tools).
- In the stream: `assistant` events carry `tool_use` blocks (name, input);
  `user` events carry the matching `tool_result`; the final `result` event has
  turn and cost totals.

### Antigravity CLI (`agy`)

Verified with `agy` 1.2.14. (Antigravity CLI replaced Gemini CLI.)

- **Server config, project-level:** `.agents/mcp_config.json` in the scratch
  directory, same shape as above. The agent sees servers from it (and from the
  global config, `~/.gemini/config/mcp_config.json`, which should be empty or
  without the server under test). `agy mcp list` shows only the global config.
- **Permissions are user-level only.** Headless runs auto-deny MCP calls
  ("a tool required the "mcp" permission that headless mode cannot prompt
  for") unless an allow rule exists, and `agy` reads rules only from
  `~/.gemini/antigravity-cli/settings.json` (and `~/.gemini/config/config.json`),
  not from the project. Create the settings file for the run and remove it
  afterwards (refuse to overwrite one that already exists):

  ```json
  {"permissions": {"allow": ["mcp(myapp/*)"],
                   "deny": ["command(*)", "write_file(*)"]}}
  ```

  Avoid `--dangerously-skip-permissions`: it approves every tool, including
  shell.

```bash
cd "$SCRATCH" && agy -p "<task prompt>" --output-format stream-json \
  --print-timeout 600s < /dev/null
```

- `agy` reads MCP tool descriptions, and large tool outputs, as files in its
  own directory via the read-only `view_file` built-in; expect those calls.
- In the stream: `step_update` events with `step_type: "tool"` and
  `state: "DONE"`; MCP calls are `tool_name: "call_mcp_tool"` with
  `ServerName`, `ToolName`, and `Arguments`. Tool **results are not in the
  stream**: judge by the calls and the end state (e.g. compare the data's
  revision before and after each write).
