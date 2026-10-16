#!/usr/bin/env python3
"""Keep a record of the story workers in flight, so a cleared or new session can find them again. Stdlib only.

The orchestrator's conversation is the only place that knows which agent works on which story. A /clear or
/compact loses that. This registry keeps it on disk, in the main checkout's .claude/worktrees/workers.json
(.claude/worktrees/ is gitignored by setup), one entry per story.

Usage (from anywhere inside the repo, the main checkout or a story worktree):
  workers.py record <ID> --launching --base <sha> [--replace] [--branch B] [--brief -|FILE]
                         record a worker about to launch, before the Agent call (no agent id yet); over an
                         entry that isn't merged or dead only with --replace
  workers.py record <ID> --agent <agent-id> [--base <sha>] [--branch B] [--worktree PATH] [--brief -|FILE]
                         record a launched worker, or fill in the agent id of a `launching` entry (which keeps
                         its base and brief); --brief - reads the launch prompt from stdin
  workers.py set <ID> <state> [--note TEXT]
                         update a worker's state: running, reported, fix-round, waiting-user, merged
  workers.py list [--json]
                         one line per worker: story, state, agent, branch, worktree (and whether it still exists)
  workers.py show <ID>   the whole entry, the launch brief included
  workers.py forget <ID> remove the entry (after the merge and the worktree cleanup)
  workers.py context <ID>
                         the worker's context size and idle time, from its transcript, and whether a fix round
                         should resume it or start a fresh worker (story-start --continue)
Options: --registry PATH (default: <main checkout>/.claude/worktrees/workers.json)
         --transcripts DIR (default: ~/.claude/projects; where `context` looks for agent-<id>.jsonl)

Every change (record, set, forget) holds an exclusive lock on workers.json.lock, next to the registry, for its
whole load-modify-save, and writes through a temp file and a rename. Parallel calls never lose an entry, and a
reader never sees a half-written file.

An agent id reaches its worker only from the session that launched it. A new session continues the story with
a fresh worker (story-start --continue): it removes the old, clean worktree and the new worker switches onto the
story branch, with `show <ID>`'s brief plus the story's backlog notes.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATES = ("running", "reported", "fix-round", "waiting-user", "merged")
# Written before the Agent call, so a launch whose agent id never got recorded still shows in `list`.
# `record --agent` moves it to running.
LAUNCHING = "launching"
# States `record --launching` may overwrite without --replace: the old worker is finished.
REPLACEABLE = ("merged", "dead")
REGISTRY_NAME = Path(".claude") / "worktrees" / "workers.json"
# A subagent's prompt cache lives 5 minutes. Resuming a worker idle for longer rewrites its whole context to the
# cache; above FRESH_WORKER_TOKENS a fresh worker with a short brief costs less and carries no stale context.
CACHE_TTL_MINUTES = 5
FRESH_WORKER_TOKENS = 150_000
AGENT_ID = re.compile(r"[A-Za-z0-9_-]+")


def main_checkout() -> Path:
    """The main checkout's root, also when called from inside a story worktree."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected a JSON object of story entries")
    return data


@contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on the registry's lock file. Closing the file releases it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def save(path: Path, data: dict[str, dict[str, object]]) -> None:
    """Write the registry atomically: a temp file in the same folder, flushed, then renamed over it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def entry(data: dict[str, dict[str, object]], sid: str) -> dict[str, object]:
    if sid not in data:
        raise SystemExit(f"no worker recorded for {sid} (see `workers.py list`)")
    return data[sid]


def option(args: list[str], name: str) -> str | None:
    """Pop `--name value` from args and return the value."""
    if name not in args:
        return None
    i = args.index(name)
    if i + 1 >= len(args):
        raise SystemExit(f"{name} needs a value")
    value = args[i + 1]
    del args[i : i + 2]
    return value


def read_brief(source: str | None) -> str | None:
    if source is None:
        return None
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def new_entry(sid: str, base: str, branch: str | None, worktree: str | None, brief: str | None) -> dict[str, object]:
    """A fresh `launching` entry, with no agent id yet."""
    return {
        "story": sid,
        "agent_id": "",
        "base_sha": base,
        "branch": branch or f"story/{sid}-*",
        "worktree": worktree or "",
        "brief": brief or "",
        "state": LAUNCHING,
        "note": "",
        "launched": now(),
        "updated": now(),
    }


def cmd_record(data: dict[str, dict[str, object]], sid: str, args: list[str], brief: str | None) -> None:
    launching, replace = "--launching" in args, "--replace" in args
    agent, base = option(args, "--agent"), option(args, "--base")
    branch, worktree = option(args, "--branch"), option(args, "--worktree")
    if launching:
        if agent or not base:
            raise SystemExit("record --launching needs --base <sha> and no --agent (the id comes after the launch)")
        state = data.get(sid, {}).get("state")
        if state is not None and state not in REPLACEABLE and not replace:
            raise SystemExit(f"{sid} is {state}: add --replace to launch a new worker over it (story-start --continue)")
        data[sid] = new_entry(sid, base, branch, worktree, brief)
        print(f"Recorded {sid}: launching, base {base[:12]}.")
        return
    if not agent:
        raise SystemExit("record needs --agent <agent-id> and --base <sha>")
    if not AGENT_ID.fullmatch(agent):
        raise SystemExit(f"--agent {agent!r}: an agent id has only letters, digits, '-' and '_'")
    previous = data.get(sid)
    is_filling = previous is not None and previous.get("state") == LAUNCHING
    if not is_filling and not base:
        raise SystemExit(f"record needs --agent <agent-id> and --base <sha> ({sid} has no `launching` entry)")
    if is_filling:
        given = {"base_sha": base, "branch": branch, "worktree": worktree, "brief": brief}
        start = {**previous, **{key: value for key, value in given.items() if value is not None}}
    else:
        start = new_entry(sid, str(base), branch, worktree, brief)
    data[sid] = {**start, "agent_id": agent, "state": "running", "updated": now()}
    print(f"Recorded {sid}: agent {agent}, base {str(data[sid]['base_sha'])[:12]}.")


def cmd_set(data: dict[str, dict[str, object]], sid: str, args: list[str]) -> None:
    note = option(args, "--note")
    if len(args) != 1 or args[0] not in STATES:
        raise SystemExit(f"set needs one state: {', '.join(STATES)}")
    e = entry(data, sid)
    if e.get("state") == LAUNCHING:
        raise SystemExit(f"{sid} is launching with no agent id: fill it with `record {sid} --agent <id>` first")
    e["state"] = args[0]
    if note is not None:
        e["note"] = note
    e["updated"] = now()
    print(f"{sid}: {args[0]}" + (f" ({note})" if note else ""))


def worktree_status(path: str) -> str:
    if not path:
        return "worktree unknown"
    return "worktree present" if Path(path).is_dir() else "worktree GONE"


def cmd_list(data: dict[str, dict[str, object]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(list(data.values()), indent=2))
        return
    if not data:
        print("No workers recorded.")
        return
    for sid in sorted(data):
        e = data[sid]
        note = f" — {e['note']}" if e.get("note") else ""
        agent = f"agent {e['agent_id']}" if e.get("agent_id") else "no agent id yet"
        print(
            f"{sid}: {e['state']}, {agent}, {e['branch']}, "
            f"{worktree_status(str(e.get('worktree', '')))} (updated {e['updated']}){note}"
        )


def cmd_show(data: dict[str, dict[str, object]], sid: str) -> None:
    e = dict(entry(data, sid))
    brief = e.pop("brief", "")
    for key in sorted(e):
        print(f"{key}: {e[key]}")
    print("\nbrief:\n" + (str(brief) or "(none recorded)"))


def turn_of(line: str) -> tuple[int, datetime] | None:
    """A transcript line's context size (input + cache tokens) and time, if it is a real model turn.

    Error and limit records (model "<synthetic>", all usage 0) and malformed lines are not turns."""
    try:
        record = json.loads(line)
        message = record["message"]
        usage = message["usage"]
        tokens = sum(int(usage.get(k) or 0) for k in
                     ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        at = datetime.fromisoformat(str(record["timestamp"]).replace("Z", "+00:00"))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
    if tokens == 0 or at.tzinfo is None:
        return None
    return tokens, at


def last_turn(transcript: Path) -> tuple[int, datetime] | None:
    """The context size and time of the transcript's last real model turn."""
    turns = (turn_of(line) for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines())
    found = None
    for turn in turns:
        found = turn or found
    return found


def cmd_forget(data: dict[str, dict[str, object]], sid: str) -> None:
    entry(data, sid)
    del data[sid]
    print(f"Forgot {sid}.")


def cmd_context(data: dict[str, dict[str, object]], sid: str, root: Path) -> None:
    agent = str(entry(data, sid).get("agent_id") or "")
    if not agent:
        raise SystemExit(f"{sid}: no agent id recorded yet (it is still `launching`)")
    if not AGENT_ID.fullmatch(agent):
        raise SystemExit(f"{sid}: recorded agent id {agent!r} isn't a plain id")
    matches = sorted(root.glob(f"*/*/subagents/agent-{agent}.jsonl"), key=lambda p: p.stat().st_mtime)
    turn = last_turn(matches[-1]) if matches else None
    if turn is None:
        print(f"{sid}: no transcript with usage found for agent {agent}; resume it (SendMessage) as usual.")
        return
    tokens, at = turn
    idle = (datetime.now(timezone.utc) - at).total_seconds() / 60
    fresh = idle >= CACHE_TTL_MINUTES and tokens >= FRESH_WORKER_TOKENS
    advice = ("fresh: story-start --continue with the findings as the task" if fresh
              else "resume: SendMessage to the agent")
    print(f"{sid}: context {tokens // 1000}K tokens, idle {idle:.0f} min -> {advice}")


def main(argv: list[str]) -> None:
    args = list(argv)
    registry = option(args, "--registry")
    transcripts = Path(option(args, "--transcripts") or Path.home() / ".claude" / "projects")
    path = Path(registry) if registry else main_checkout() / REGISTRY_NAME
    if not args:
        raise SystemExit(__doc__)
    command, rest = args[0], args[1:]
    if command == "list":
        cmd_list(load(path), "--json" in rest)
        return
    if not rest:
        raise SystemExit(f"{command} needs a story ID")
    sid, rest = rest[0], rest[1:]
    if command == "show":
        cmd_show(load(path), sid)
    elif command == "context":
        cmd_context(load(path), sid, transcripts)
    elif command in ("record", "set", "forget"):
        # Read the brief before taking the lock: a slow stdin must not hold up the other writers.
        brief = read_brief(option(rest, "--brief")) if command == "record" else None
        with locked(path):
            data = load(path)
            if command == "record":
                cmd_record(data, sid, rest, brief)
            elif command == "set":
                cmd_set(data, sid, rest)
            else:
                cmd_forget(data, sid)
            save(path, data)
    else:
        raise SystemExit(f"unknown command {command!r}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
