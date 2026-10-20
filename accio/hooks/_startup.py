"""Start-up crash handling shared by the guards (decision 007: guards fail open).

Stdlib only, so it loads even when `accio_lib` won't. A guard imports this first, then tries `accio_lib`; on a
failed import its `main` calls `handle_crash`. An accio agent's call is denied naming the error, since it can't be
checked; the main chat, other agents and `PermissionRequest` get no answer, so a broken update never blocks anyone
else.
"""
import json

AGENT_PREFIX = "accio:"


def crash_message(error):
    return f"could not start ({type(error).__name__}: {error})."


def is_accio_call(raw):
    """True when `raw` is a PreToolUse input from an `accio:*` agent."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict) or data.get("hook_event_name") == "PermissionRequest":
        return False
    agent = data.get("agent_type")
    return isinstance(agent, str) and agent.startswith(AGENT_PREFIX)


def handle_crash(raw, error, deny):
    """Call `deny(message)` for an accio agent's call; return the hook's exit code, which is the deny's result
    (or 0 when nothing is denied)."""
    if not is_accio_call(raw):
        return 0
    return deny(crash_message(error))
