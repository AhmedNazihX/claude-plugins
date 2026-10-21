# Spike S-L5: a real mad-eye click payload (S-059)

Date: 2026-10-21, by hand. Claude Code 2.1.306, accio 0.9.0 from this repo (`--plugin-dir accio`), the
`playwright` plugin's MCP server (tools `mcp__plugin_playwright_playwright__*`).

## Verdict
**Yes: `- Page URL:` appears in the `tool_response` with default settings.** It is there after a click, a navigate
and a snapshot, and it shows the page the browser ended on, also after a redirect to another origin. The fence
(S-063, S-064) can go ahead as designed, with the changes below.

## Setup
- A scratch git repo with `.accio/config.json` holding a full `preview` (`command`, `url: http://127.0.0.1:8765`,
  `test_data: true`).
- Two local servers. The preview on `127.0.0.1:8765` has one link, "Details", to `/details`, which answers
  `302 Location: http://localhost:8766/`. The other origin, `localhost:8766`, serves a page titled "Elsewhere".
- A logging hook passed with `--settings`: PostToolUse, matcher `mcp__.*__browser_.*`, appending stdin to a file.
- `claude -p --model sonnet --plugin-dir <repo>/accio --settings <hook> --allowedTools Agent`, prompt on stdin. The
  main agent called the Agent tool once with `subagent_type: accio:mad-eye`: navigate to the preview, full snapshot,
  click "Details", full snapshot, close.

## What the payload looks like
The click's payload is the fixture `accio/tests/fixtures/browser-click-offorigin.json`, as captured. Only
`transcript_path` and `cwd` were shortened to `<home>/…` and `<scratch>/…`, to keep local paths out of the repo.

- Keys: `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `agent_id`, `agent_type`, `effort`,
  `hook_event_name`, `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `duration_ms`, `mcp_server`.
- `agent_type` is `accio:mad-eye`; `agent_id` is set (here `a9549e371ba1e3b80`).
- `tool_response` is a **list of content blocks**, not a string: here one `{"type": "text", "text": …}`.
- `tool_input` for a click is `{"target": "e4", "element": "Details link"}`.
- The text, in sections:

  ~~~
  ### Ran Playwright code
  ```js
  await page.getByRole('link', { name: 'Details' }).click();
  ```
  ### Page
  - Page URL: http://localhost:8766/
  - Page Title: Elsewhere
  ### Snapshot
  - [Snapshot](.playwright-mcp/page-2026-10-21T11-02-23-314Z.yml)
  ~~~

| Tool | `- Page URL:` line | Snapshot |
|---|---|---|
| `browser_navigate` | yes | a link to a `.playwright-mcp/page-*.yml` file |
| `browser_snapshot` | yes | inline YAML |
| `browser_click` | yes, the page after the click (after the redirect) | a link to a `.playwright-mcp/page-*.yml` file |
| `browser_close` | **no** (`### Result` "No open tabs…") | none |

## Findings
1. **Page URL is there by default**, on its own line, `- Page URL: <url>`, inside `### Page`. The click's line shows
   where the redirect landed, not the link's `href` (`/details`).
2. **`tool_response` is a list.** The hook must read the `text` of each `type: text` block, not treat the response
   as one string.
3. **`browser_close` has no Page URL.** A response without the line must leave the fence as it is (neither set nor
   lift it).
4. **The page also lands in a file mad-eye can read.** After the click, `.playwright-mcp/page-…yml` held the
   off-origin page (`heading "Another origin"`). mad-eye has `Read`, `Grep` and `Glob`, so hiding the tool response
   alone leaves the page readable from that folder. S-063 or S-064 must close this: for example, while fenced,
   curfew denies mad-eye reads under `.playwright-mcp/`.
5. **mad-eye keeps to the preview when it can see the link.** In a first run the link's `href` was
   `http://localhost:8766/`; mad-eye read it in the snapshot and refused to click. The fence is for the case it
   cannot see: a same-origin link that redirects away, as here.
6. **A bad `preview` blocks every mad-eye call.** In the first try `preview` had only `url`; curfew denied every
   call (`Read` and the reply too) with `preview must be {"command": …, "url": …, "test_data": true}`. Fail-closed
   is right; the message is clear.

## What this changes
- **S-063 (fence hook):** read `Page URL` from the text blocks of the list; a response without the line changes
  nothing; use this fixture (with the URL changed to `http://evil.com/` for the off-origin case, as planned, though
  it is already off-origin as captured).
- **S-063 or S-064:** close finding 4, the `.playwright-mcp/` snapshot files, while fenced.
