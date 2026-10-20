#!/usr/bin/env python3
"""curfew: the permission policy for accio's agents (DESIGN § 4.4; decision 010; spike S-015).

PreToolUse, every tool: answers `allow` or `deny` (with the reason) for every call by an `accio:*` agent, from
`accio_lib.policy`, so none waits on a permission question. An allowed call that matches an `ask` rule in the
settings is denied instead, naming the rule: inside a workflow that question would freeze the agent, and a hook's
`deny` beats a rule's `ask`. A claim (`accio-claim <ID>`) is recorded in `run/claims.json`.

PermissionRequest: no hook answer counts inside a workflow agent (spike S-015), so this only records the agent,
tool and command in `run/stuck.json`, for `map` and `owl` to show what froze.

Other callers get no answer and go through the normal permission flow. Exits 0 silently in a repo without
`.accio/` and on bad input. A call it fails to check is denied. If `accio_lib` won't import, an accio agent's call
is denied naming the error and everyone else gets no answer (guards fail open, decision 007).
"""
import json
import os
import pathlib
import sys
import time

HOOKS = pathlib.Path(__file__).resolve().parent
BIN = HOOKS.parent / "bin"
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(BIN))

import _startup  # noqa: E402  (stdlib only, so it loads even when `accio_lib` doesn't)

AGENT_PREFIX = _startup.AGENT_PREFIX

try:
    from accio_lib import askrules, config, paths, policy, runlock  # noqa: E402
    STUCK_NAME = runlock.STUCK_NAME
    IMPORT_ERROR = None
except Exception as import_error:  # noqa: BLE001 — a start-up crash is handled in `_startup_crash`, never raised
    IMPORT_ERROR = import_error


def _payload(raw):
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return None
    agent = payload.get("agent_type")
    if not isinstance(agent, str) or not agent.startswith(AGENT_PREFIX) or agent == AGENT_PREFIX:
        return None
    return payload


def _read_json(path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _answer(allowed, reason):
    output = {"hookEventName": "PreToolUse", "permissionDecision": "allow" if allowed else "deny"}
    if reason:
        output = {**output, "permissionDecisionReason": f"curfew (accio's gatekeeper for build agents): {reason}"}
    print(json.dumps({"hookSpecificOutput": output}))


def _record_claim(run_dir, agent_id, story_id, worktree):
    """Record a claim, unless another agent holds the story (`accio-brief` releases it for a fix round); returns
    the reason it was refused, or None."""
    with runlock.guard(run_dir):
        claims = _read_json(run_dir / runlock.CLAIMS_NAME, {})
        holder = next((other for other, held in claims.items()
                       if isinstance(held, dict) and held.get("story") == story_id and other != agent_id), None)
        if holder:
            return f"{story_id} is already claimed by agent {holder}; its next brief releases it."
        _write_json(run_dir / runlock.CLAIMS_NAME, {**claims, agent_id: {"story": story_id, "worktree": worktree}})
    return None


def _record_stuck(run_dir, payload):
    tool_input = payload["tool_input"]
    detail = next((tool_input[key] for key in ("command", "file_path", "notebook_path", "url")
                   if isinstance(tool_input.get(key), str)), "")
    entry = {"agent_id": payload.get("agent_id"), "agent_type": payload["agent_type"],
             "tool": payload.get("tool_name"), "detail": detail, "time": int(time.time())}
    with runlock.guard(run_dir):
        _write_json(run_dir / STUCK_NAME, [*_read_json(run_dir / STUCK_NAME, []), entry])


def _claims(run_dir):
    claims = _read_json(run_dir / runlock.CLAIMS_NAME, {})
    return {agent: held for agent, held in claims.items()
            if isinstance(held, dict) and isinstance(held.get("story"), str) and isinstance(held.get("worktree"), str)}


def _settings(accio, run_dir, story_id):
    """config.json, with the commands owl allowed once for this agent's story added to `agent_allow` (S-022): a grant
    is for one story's next build, not for every story in it."""
    settings = config.load(accio)
    once = _read_json(run_dir / runlock.ALLOW_ONCE_NAME, {})
    stories = once.get("stories", {}) if isinstance(once, dict) else {}
    commands = stories.get(story_id, []) if isinstance(stories, dict) and story_id else []
    extra = [command for command in commands if isinstance(command, str)] if isinstance(commands, list) else []
    return {**settings, "agent_allow": [*settings.get("agent_allow", []), *extra]}


def _statuses(run_dir):
    statuses = _read_json(run_dir / "status.json", {})
    return {story: status for story, status in statuses.items() if isinstance(status, str)}


def _pre_tool_use(payload, root, accio):
    run_dir = accio / "run"
    agent, agent_id = payload["agent_type"][len(AGENT_PREFIX):], str(payload.get("agent_id", ""))
    claims = _claims(run_dir)
    context = policy.Context(root=root, accio=accio, bin_dir=BIN,
                             config=_settings(accio, run_dir, claims.get(agent_id, {}).get("story")),
                             claims=claims, statuses=_statuses(run_dir))
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else ""
    decision = policy.decide(agent, agent_id, tool, payload["tool_input"], context)
    if not decision.allow:
        return False, decision.reason
    rule = askrules.first_match(askrules.ask_rules(root, pathlib.Path.home()), tool, payload["tool_input"])
    if rule:
        return False, (f"your settings ask before this (`{rule.text}` in {rule.source}), and an agent in a build "
                       "can't ask, so it would freeze. Remove the rule, or allow the call at owl.")
    refused = _record_claim(run_dir, agent_id, *decision.claim) if decision.claim else None
    return (False, refused) if refused else (True, decision.reason)


def _deny_crash(message):
    _answer(False, message)
    return 0


def main():
    if IMPORT_ERROR is not None:
        return _startup.handle_crash(sys.stdin.read(), IMPORT_ERROR, _deny_crash)
    payload = _payload(sys.stdin.read())
    if payload is None:
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload["cwd"]) else os.getcwd()
    try:
        accio = paths.accio_dir(cwd)
    except (OSError, ValueError):
        return 0
    if accio is None:
        return 0
    root = accio.parent
    if payload.get("hook_event_name") == "PermissionRequest":
        try:
            _record_stuck(accio / "run", payload)
        except Exception:  # noqa: BLE001 — a record that can't be written must not answer the question
            pass
        return 0
    try:
        allowed, reason = _pre_tool_use(payload, root, accio)
    except Exception as error:  # noqa: BLE001 — a policy that crashes must say no, not leave a question to freeze on
        allowed, reason = False, f"could not check this call ({type(error).__name__}: {error})."
    _answer(allowed, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
