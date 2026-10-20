# Spikes S-M2 and S-M3: browser tools in a build (S-044)

Date: 2026-10-20. Run by hand in the main session with the user, while iteration 11's build ran. Claude Code with
the `playwright` plugin's MCP server (tools `mcp__plugin_playwright_playwright__*`).

## Verdict
**Go for mad-eye.** A Workflow `agent()` can drive the Playwright MCP server, both when it loads the tools on demand
and when its `tools:` frontmatter lists them by name. An agent that names a missing MCP server gets a plain error and
keeps running. Two findings change S-046 and S-047 (see "What this changes").

## Setup
- A one-file page served by `python3 -m http.server 8765 --bind 127.0.0.1` from a scratch folder: a `#token`
  paragraph reading `marker-7f3a` and a "Click me" button that sets it to `clicked-9b2c`.
- One toy workflow (`spike-s-m2-m3`) with three agents in parallel. Two agent types were temporary files in
  `~/.claude/agents/` (`spike-mcp-listed`, `spike-mcp-missing`), removed afterwards.
- Each agent: navigate, read `#token`, click, read again, screenshot; may use no Bash.

## S-M2: does a workflow agent get the session's MCP tools? Pass.
| Agent | How it got the tools | Navigate | Click changed the text | Screenshot on disk |
|---|---|---|---|---|
| plain workflow agent (default type) | deferred; loaded with ToolSearch `select:` | yes | `marker-7f3a` → `clicked-9b2c` | yes, 1200×686 PNG, shows `clicked-9b2c` |
| `tools:` lists four Playwright tools | loaded directly, only those four | yes | `marker-7f3a` → `clicked-9b2c` | yes, 1200×686 PNG at `.accio/run/spike-s-m2/listed.png` |

## S-M3: `tools:` names an MCP server the session lacks. Pass.
The agent's tool list held only `Read` and `StructuredOutput`. Calling `mcp__nosuchserver__do_thing` failed at once
with `Error: No such tool available: mcp__nosuchserver__do_thing`, and the agent went on and returned its report.
No hang, no load error for the agent.

## Findings
1. **Screenshots must land inside the repo.** The MCP server refused a path outside the workspace: "File access
   denied: … is outside allowed roots. Allowed roots: <repo>/.playwright-mcp, <repo>". A relative filename resolves
   against the repo root (the plain agent's `plain.png` landed in the repo root). An absolute path under
   `.accio/run/` was accepted.
2. **The server writes logs into the repo root.** Every session wrote `page-*.yml` and `console-*.log` files to
   `<repo>/.playwright-mcp/`. In a build, that is a new untracked folder in the main checkout, so the main-checkout
   snapshot (which hashes untracked and ignored paths) would block the story as `main_changed`.
3. **Refs go stale after a scoped snapshot.** Both browsing agents' first click failed with "Ref … not found in the
   current page snapshot" after a snapshot with a `target`; a fresh full snapshot fixed it. mad-eye's instructions
   should say: take a full snapshot before each click.
4. **`tools:` limits an agent to the listed tools.** The listed agent saw only its four browser tools, so mad-eye's
   frontmatter can name exactly the allowed set (S-046's list), with curfew as the second wall.
5. The page load reported "Console: 1 errors" (the server's missing favicon); harmless here, but mad-eye should not
   count console errors as findings unless a DoD line names them.

## What this changes
- **S-047 (mad-eye):** screenshots go to an absolute path under `.accio/run/<ID>/mad-eye/` (inside the allowed root,
  outside the snapshot); a full snapshot before each click; `tools:` lists the allowed browser tools.
- **S-046 or S-049:** `.playwright-mcp/` in the main checkout must not count as `main_changed` (add it to the
  snapshot's skipped paths), or a mad-eye story blocks on its own logs.
- **S-045:** unchanged.
