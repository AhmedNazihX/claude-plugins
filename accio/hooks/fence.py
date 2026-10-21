#!/usr/bin/env python3
"""fence: the PostToolUse hook that hides an off-origin page from mad-eye (DESIGN § 4.4; spike S-L5).

Curfew checks only `browser_navigate`, but a click can leave the preview too. After a browser tool call by
`accio:mad-eye`, this reads every `- Page URL:` line of the response (a list of content blocks). If any is off the
origin of `preview.url`, or a `### Page` section has no readable one, it returns `updatedMCPToolOutput` with the reason
in place of the page, logs the call, and records the fence in `run/mad-eye-fence.json` (`{agent_id: {"url": ...}}`).
A response all on the origin lifts that agent's fence. A response with no page is hidden while the agent is fenced;
unfenced, a screenshot or console response is replaced too (it doesn't show the page is on the preview, S-066) and
any other (a close) passes. Any other agent: nothing changes.
Fails open (decision 007): any crash adds no output.
"""
import datetime
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

AGENT = "accio:mad-eye"
PAGE_URL = re.compile(r"^- Page URL: (.*)$", re.MULTILINE)
PAGE_SECTION = re.compile(r"^### Page\s*$", re.MULTILINE)
NO_URL = "(a page with no readable Page URL line)"
SHOT_TOOL = "browser_take_screenshot"
CONSOLE_TOOL = "browser_console_messages"
LOG_NAME = "mad-eye-fence.log"
URL_SHOWN = 200


def _page_urls(response):
    """Every `Page URL` in a tool response's text blocks, and whether any block has a `### Page` section."""
    blocks = response if isinstance(response, list) else []
    texts = [block["text"] for block in blocks
             if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)]
    urls = [url.strip() for text in texts for url in PAGE_URL.findall(text)]
    return urls, any(PAGE_SECTION.search(text) for text in texts)


def _read_map(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_map(path, data):
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _update_fence(run_dir, agent_id, url):
    """Add (url given) or lift (url None) the agent's key, keeping the others."""
    from accio_lib import runlock
    path = run_dir / runlock.FENCE_NAME
    with runlock.guard(run_dir):
        fence = _read_map(path)
        if url is None and agent_id not in fence:
            return
        _write_map(path, {**{k: v for k, v in fence.items() if k != agent_id},
                          **({agent_id: {"url": url}} if url is not None else {})})


def _log_path(run_dir, agent_id):
    from accio_lib import runlock
    held = _read_map(run_dir / runlock.CLAIMS_NAME).get(agent_id)
    story = held.get("story") if isinstance(held, dict) else None
    folder = run_dir / story if isinstance(story, str) and re.fullmatch(r"[A-Za-z0-9._-]+", story) else run_dir
    return folder / LOG_NAME


def _log(run_dir, agent_id, tool, url):
    path = _log_path(run_dir, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{now} {agent_id} {tool} {_shown(url)}\n")


def _shown(url):
    """The URL may come from the page: show one short word, never a sentence or a line break."""
    return (url.split() or [NO_URL])[0][:URL_SHOWN]


def _record(run_dir, agent_id, tool, url):
    """Write the fence record and the log line. Best effort: the page is hidden even when this fails."""
    try:
        _update_fence(run_dir, agent_id, url)
        _log(run_dir, agent_id, tool, url)
    except (OSError, ValueError) as error:
        print(f"fence: could not record the fence for {agent_id}: {error}", file=sys.stderr)


def _reason(url, preview):
    return (f"fence (accio's preview fence): this page, {_shown(url)}, is off the preview's origin, so it is hidden. "
            f"Call browser_navigate to go back to the preview, {preview}.")


def _hide(url, preview):
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": [
        {"type": "text", "text": _reason(url, preview)}]}}


def _replace(text):
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": [
        {"type": "text", "text": text}]}}


def _unverified(payload):
    """S-066: a screenshot or console response with no `Page URL` does not show the page is on the preview."""
    tool = str(payload.get("tool_name", ""))
    if tool.endswith(SHOT_TOOL):
        given = (payload.get("tool_input") or {}).get("filename")
        name = " ".join(given.split())[:URL_SHOWN] if isinstance(given, str) and given.strip() else None
        where = f"to {name}" if name else "to the file it was given"
        return _replace(f"fence (accio's preview fence): the screenshot was saved {where}, but the picture is hidden "
                        f"because the response doesn't show the page is on the preview. Check the page with "
                        f"browser_snapshot.")
    if tool.endswith(CONSOLE_TOOL):
        return _replace("fence (accio's preview fence): this response can't be shown because it doesn't show the "
                        "page is on the preview. Check the page with browser_snapshot.")
    return None


def _act(payload):
    """The hook's output for one payload, or None."""
    from accio_lib import config, paths, policy, runlock
    if payload.get("agent_type") != AGENT:
        return None
    urls, has_page = _page_urls(payload.get("tool_response"))
    accio = paths.guarding_accio_dir(payload.get("cwd"))
    if accio is None:
        return None
    preview = (config.load(accio).get("preview") or {}).get("url")
    wanted = policy._origin(preview) if isinstance(preview, str) else None
    if wanted is None:
        return None
    run_dir, agent_id = accio / "run", str(payload.get("agent_id", ""))
    if not urls and not has_page:  # no page in this response: hidden only while fenced
        try:
            held = _read_map(run_dir / runlock.FENCE_NAME).get(agent_id)
        except (OSError, ValueError):  # a fence file we can't read may be holding this agent: hide
            return _hide(NO_URL, preview)
        if isinstance(held, dict):
            return _hide(str(held.get("url", NO_URL)), preview)
        return _unverified(payload)
    off = [url for url in urls if policy._origin(url) != wanted]
    if urls and not off:
        _update_fence(run_dir, agent_id, None)
        return None
    url = off[0] if off else NO_URL  # a `### Page` section with no readable URL counts as off the origin
    hidden = _hide(url, preview)
    _record(run_dir, agent_id, str(payload.get("tool_name", "")), url)
    return hidden


def main():
    try:
        payload = json.loads(sys.stdin.read())
        output = _act(payload) if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 — fail open (decision 007): a crash adds no output
        return 0
    if output:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
