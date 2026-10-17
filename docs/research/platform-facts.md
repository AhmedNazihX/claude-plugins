# Platform facts (checked 2026-10-17, Claude Code CLI 2.1.302)

These facts were checked against code.claude.com docs by a fact-check agent. UNKNOWN means not documented, so
treat it as unavailable until a spike proves it.

## Workflows
- **Plugins can ship workflows.** They go in `workflows/<name>.js` (or the manifest key `"workflows"`) and are
  invoked as `/<plugin>:<name>`, or through the `Workflow` tool with `name`.
  ([docs](https://code.claude.com/docs/en/workflows#distribute-a-workflow-in-a-plugin))
- **Opt-in rules.**
  - A human typing the slash command counts as opt-in.
  - Whether a plugin skill's instruction to call Workflow also counts: UNKNOWN.
  - Permissions apply. Manual mode prompts per run, with "don't ask again" for named plugin workflows.
- **`agent()` options.**
  - Documented: `schema` (structured JSON, retried up to 5×), `stallMs`, `label`. You can choose a model per stage.
  - Using a plugin's named subagent type: UNKNOWN.
  - Worktree isolation: UNKNOWN (only subagent frontmatter has `isolation: worktree`).
- **No pause for the user inside a run.** Split work into separate workflows wherever the user must sign off.
- **Limits:** 16 concurrent agents, 1,000 agents per run.

## Evals
`claude plugin eval` reads its suite from `evals/<case>/`:
- `prompt.md` (frontmatter: `runs`, `max_turns`, `model`, `allowed_tools`, …)
- `graders/*.md`. The free graders are `regex`, `tool_used`, `tool_order` and `file_exists`. The `llm` and
  `baseline` graders call a judge model and cost money.

Cost controls: `--max-cost-usd`, `--runs`, `--threshold`. Each case runs in an isolated sandbox.
([docs](https://code.claude.com/docs/en/plugin-evals))

## Hooks ([docs](https://code.claude.com/docs/en/hooks))
- **`if`** takes one permission-rule string, for example `"if": "Bash(git commit *)"`. It is best-effort: when the
  command can't be parsed, the hook runs anyway.
- **`async`** runs the hook in the background. **`asyncRewake`** wakes Claude on exit 2, passing stderr.
  `rewakeMessage` does not exist.
- **Exit 2 on PreToolUse blocks** any matched tool, Bash, Edit and Write included, and it also blocks in
  `bypassPermissions`/`dontAsk` mode.
- **JSON `permissionDecision`** takes `allow`, `deny`, `ask` or `defer`. The order of precedence is
  deny > defer > ask > allow.
- **`continueOnBlock: true`** lets the turn carry on after a block. This is in the hooks guide but not confirmed on
  the reference page.

## Prompt cache and subagents ([docs](https://code.claude.com/docs/en/prompt-caching))
- **Subagents default to a 5-minute TTL.** Override it with `subagentPromptCacheTtl` /
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` (`5m` or `1h`), or per agent with `experimental.cacheTtl`.
- **Resuming an agent after its TTL** has expired re-processes the whole prefix.
- **A model change means a separate cache.** Effort changes also invalidate the cache on most models.
- **Subagent frontmatter:**
  - Fields: `model`, `effort`, `isolation: worktree`, `tools`, `disallowedTools`, `maxTurns`, `skills`, `memory`,
    `background`, `experimental`.
  - Plugin agents ignore `hooks`, `mcpServers` and `permissionMode`.

## Plugin components ([docs](https://code.claude.com/docs/en/plugins/components))
- **Supported:** skills, agents, hooks, commands, output styles, workflows, `.mcp.json`, `.lsp.json`, monitors,
  `bin/` (on the Bash PATH), themes, `userConfig`.
- **Not supported:** plugin-shipped `.claude/rules`, setting the main statusLine, a plugin-root CLAUDE.md.
  Workarounds:
  - an output style, or a short SessionStart injection, for always-on guidance
  - a skill with `paths` frontmatter, for guidance scoped to files
- **Context cost:** only skill descriptions load at session start; the description plus `when_to_use` is truncated at
  1,536 characters. `claude plugin details <name>` shows the projected token cost.
