#!/usr/bin/env python3
"""fence: the PostToolUse hook that hides an off-origin page from mad-eye (DESIGN § 4.4; spike S-L5).

Curfew checks only `browser_navigate`, but a click can leave the preview too. After a browser tool call by
`accio:mad-eye`, this reads the `- Page URL:` line of the response (a list of content blocks; the first `text`
block with such a line counts). Off the origin of `preview.url`, it returns `updatedMCPToolOutput` with the reason in
place of the page, logs the call, and records the fence in `run/mad-eye-fence.json` (`{agent_id: {"url": ...}}`).
A response on the origin lifts that agent's fence. No `Page URL` line, or any other agent: nothing changes.
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
PAGE_URL = re.compile(r"^- Page URL: (\S+)\s*$", re.MULTILINE)
LOG_NAME = "mad-eye-fence.log"


def _page_url(response):
    """The first `Page URL` in a tool response's text blocks, or None."""
    if not isinstance(response, list):
        return None
    for block in response:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            found = PAGE_URL.search(block["text"])
            if found:
                return found.group(1)
    return None


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
        handle.write(f"{now} {agent_id} {tool} {url}\n")


def _reason(url, preview):
    return (f"fence (accio's preview fence): this page, {url}, is off the preview's origin, so it is hidden. "
            f"Call browser_navigate to go back to the preview, {preview}.")


def _act(payload):
    """The hook's output for one payload, or None."""
    from accio_lib import config, paths, policy
    if payload.get("agent_type") != AGENT:
        return None
    url = _page_url(payload.get("tool_response"))
    if url is None:
        return None
    accio = paths.guarding_accio_dir(payload.get("cwd"))
    if accio is None:
        return None
    preview = (config.load(accio).get("preview") or {}).get("url")
    wanted = policy._origin(preview) if isinstance(preview, str) else None
    if wanted is None:
        return None
    run_dir, agent_id = accio / "run", str(payload.get("agent_id", ""))
    if policy._origin(url) == wanted:
        _update_fence(run_dir, agent_id, None)
        return None
    _update_fence(run_dir, agent_id, url)
    _log(run_dir, agent_id, str(payload.get("tool_name", "")), url)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": [
        {"type": "text", "text": _reason(url, preview)}]}}


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
