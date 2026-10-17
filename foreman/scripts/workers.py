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
  workers.py handoff-path <ID> [--reviewer NAME --round N]
                         print where the worker (or reviewer NAME, in round N) writes its report file
  workers.py report <ID> [--reviewer NAME --round N] [--field status|evidence|needs-user|checks]
                         check a report file's header, then print one section (or, with no --field, the whole
                         report); exit 2 when the file or a header line is missing
  workers.py verdict <ID> <reviewer> <sha> <pass|fail> --level <level> --evidence <path>
                         append a reviewer's verdict on a commit to the ledger; level is one of live-verified,
                         test-verified, static-only, blocked, failed (a pass can't be blocked or failed)
  workers.py verdicts <ID> --head <sha> --reviewers a,b,c [--base REF]
                         exit 0 only when every named reviewer passed this head, or an earlier sha with the same
                         patch-id; else exit 2 and list what is missing
Options: --registry PATH (default: <main checkout>/.claude/worktrees/workers.json)
         --transcripts DIR (default: ~/.claude/projects; where `context` looks for agent-<id>.jsonl)
         --handoffs DIR (default: <main checkout>/.claude/worktrees/handoffs; where the report files live)
         --ledger PATH (default: <main checkout>/.claude/worktrees/ledger.tsv; where the verdicts are kept)

Report files. A worker writes its full report to handoffs/<ID>.md; a reviewer to handoffs/<ID>-<NAME>-r<N>.md,
where a ':' in NAME becomes '-' (foreman:diff-reviewer, round 1 -> R1-foreman-diff-reviewer-r1.md). The file
starts with a header: one `Key: value` line per key, in any order, before the first blank line.
  worker:   Story: <ID>        the story ID, as given to `report`
            Branch: <branch>   the story branch
            Head: <sha>        the branch head the report describes (7 to 40 hex digits)
            Agent: <agent-id>  the worker's agent id
            Time: <ISO time>   when the report was written
  reviewer: Reviewer: <NAME>   the reviewer's name, as given to --reviewer (or its file-name form)
            Range: <a>..<b>    the commit range reviewed; <b> is the head its verdict is for (two shas,
                               7 to 40 hex digits each)
            Verdict: <verdict> the reviewer's verdict
A missing key or an empty value exits 2. After the header comes the report itself, as story-worker § 5 lays it
out. --field picks one part of it:
  status      the worker's DONE, BLOCKED or NEEDS USER (from the `Story <ID> — ...` line), or the Verdict
  evidence    the `DoD evidence` section
  needs-user  the `Needs user (if any):` section
  checks      the `Checks:` section
A section runs from its label line to the next blank line or the next label line. A report without the section
exits 1.

The verdict ledger. ledger.tsv has one tab-separated row per verdict: ts, story, reviewer, sha, verdict, level,
evidence. It is append-only. Tabs, carriage returns and newlines in a cell become a space, and a cell that starts
with = + - or @ gets a leading ' so a spreadsheet never reads it as a formula. `verdict` resolves the sha to the
full commit id, so it runs inside the repo. A reviewer's latest row on a matching sha decides: a fail after a
pass voids it. An earlier sha matches the head when `git patch-id --stable` of its diff from the base branch
(--base, default foreman.json's base_branch, else main) equals the head's: a rebase that changes nothing keeps
its verdicts, a new commit voids them.

Every change (record, set, forget, verdict) holds an exclusive lock on workers.json.lock, next to the registry, for its
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
HANDOFFS_NAME = Path(".claude") / "worktrees" / "handoffs"
# Story IDs and reviewer names become file names: no '/', no '.', so no path can leave the handoffs folder.
STORY_ID = re.compile(r"[A-Za-z0-9_-]+")
REVIEWER_NAME = re.compile(r"[A-Za-z0-9_:-]+")
WORKER_HEADER = ("Story", "Branch", "Head", "Agent", "Time")
REVIEWER_HEADER = ("Reviewer", "Range", "Verdict")
HEADER_LINE = re.compile(r"([A-Za-z]+):\s*(.*)")
HEAD_SHA = re.compile(r"[0-9a-f]{7,40}")
STATUS_LINE = re.compile(r"Story\s+\S+\s+[—-]+\s+(DONE|BLOCKED|NEEDS USER)\b")
# The report's section labels (story-worker § 5). A field prints the section that starts with its label.
SECTION_LABELS = (
    "Outputs", "DoD evidence", "Checks:", "Root causes:", "Cost:", "Checklist:", "Needs user", "Choices I made",
    "Follow-ups", "Outcome note",
)
FIELDS = {"evidence": "DoD evidence", "needs-user": "Needs user", "checks": "Checks:"}
RANGE = re.compile(r"([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})")
# Exit code for a report that breaks the contract (no file, or a header line missing), and for a merge gate
# that isn't met (`verdicts` with a reviewer missing).
CONTRACT_BROKEN = 2
LEDGER_NAME = Path(".claude") / "worktrees" / "ledger.tsv"
LEDGER_COLUMNS = ("ts", "story", "reviewer", "sha", "verdict", "level", "evidence")
VERDICTS = ("pass", "fail")
LEVELS = ("live-verified", "test-verified", "static-only", "blocked", "failed")
# A pass claims the change works; a blocked or failed check can't back that claim.
NOT_A_PASS = ("blocked", "failed")
CELL_BREAKS = re.compile(r"[\t\r\n]+")
FORMULA_START = ("=", "+", "-", "@")
DEFAULT_BASE = "main"


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


def broken(message: str) -> SystemExit:
    """A report that breaks the contract: the message on stderr, exit 2."""
    print(message, file=sys.stderr)
    return SystemExit(CONTRACT_BROKEN)


def reviewer_args(args: list[str]) -> tuple[str, int] | None:
    """Pop `--reviewer NAME --round N` from args: both or neither."""
    name, round_ = option(args, "--reviewer"), option(args, "--round")
    if name is None and round_ is None:
        return None
    if name is None or round_ is None:
        raise SystemExit("--reviewer and --round go together")
    if not REVIEWER_NAME.fullmatch(name):
        raise SystemExit(f"--reviewer {name!r}: a reviewer name has only letters, digits, '-', '_' and ':'")
    if not round_.isdigit() or int(round_) < 1:
        raise SystemExit(f"--round {round_!r}: a round is a whole number from 1")
    return name, int(round_)


def handoff_path(handoffs: Path, sid: str, reviewer: tuple[str, int] | None) -> Path:
    if not STORY_ID.fullmatch(sid):
        raise SystemExit(f"story ID {sid!r}: an ID has only letters, digits, '-' and '_'")
    if reviewer is None:
        return handoffs / f"{sid}.md"
    name, round_ = reviewer
    return handoffs / f"{sid}-{name.replace(':', '-')}-r{round_}.md"


def read_header(lines: list[str]) -> dict[str, str]:
    """The `Key: value` lines before the first blank line."""
    header: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            break
        match = HEADER_LINE.fullmatch(line.strip())
        if match:
            header.setdefault(match.group(1), match.group(2).strip())
    return header


def check_header(header: dict[str, str], path: Path, sid: str, reviewer: tuple[str, int] | None) -> None:
    keys = WORKER_HEADER if reviewer is None else REVIEWER_HEADER
    missing = [key for key in keys if not header.get(key)]
    if missing:
        raise broken(f"{path}: header line missing or empty: {', '.join(missing)} (needs {', '.join(keys)})")
    if reviewer is None:
        if header["Story"] != sid:
            raise broken(f"{path}: header says Story: {header['Story']}, expected {sid}")
        if not HEAD_SHA.fullmatch(header["Head"]):
            raise broken(f"{path}: Head: {header['Head']!r} isn't a commit sha")
        return
    name = reviewer[0]
    if header["Reviewer"] not in (name, name.replace(":", "-")):
        raise broken(f"{path}: header says Reviewer: {header['Reviewer']}, expected {name}")
    if not RANGE.fullmatch(header["Range"]):
        raise broken(f"{path}: Range: {header['Range']!r} isn't <sha>..<sha>")


def is_label(line: str) -> bool:
    """A section's first line: not indented, and starting with a known label (Markdown '#' and '*' allowed)."""
    if line[:1].isspace():
        return False
    return line.lstrip("#* ").startswith(SECTION_LABELS)


def section(lines: list[str], label: str) -> str | None:
    """The lines from the label's line to the next blank line or label line, or None without the label."""
    starts = [i for i, line in enumerate(lines) if is_label(line) and line.lstrip("#* ").startswith(label)]
    if not starts:
        return None
    found = [lines[starts[0]]]
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or is_label(line):
            break
        found.append(line)
    return "\n".join(found)


def status(lines: list[str], header: dict[str, str], reviewer: tuple[str, int] | None) -> str | None:
    if reviewer is not None:
        return header["Verdict"]
    for line in lines:
        match = STATUS_LINE.search(line)
        if match:
            return match.group(1)
    return None


def cmd_report(handoffs: Path, sid: str, args: list[str]) -> None:
    field = option(args, "--field")
    reviewer = reviewer_args(args)
    if args:
        raise SystemExit(f"report: unexpected {' '.join(args)}")
    if field is not None and field != "status" and field not in FIELDS:
        raise SystemExit(f"--field {field!r}: one of status, {', '.join(FIELDS)}")
    path = handoff_path(handoffs, sid, reviewer)
    if not path.is_file():
        raise broken(f"{path}: no report file")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header = read_header(lines)
    check_header(header, path, sid, reviewer)
    if field is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    found = status(lines, header, reviewer) if field == "status" else section(lines, FIELDS[field])
    if found is None:
        raise SystemExit(f"{path}: no {field} section")
    print(found)


def git(*args: str, stdin: str | None = None) -> str | None:
    """A git command's stdout, or None when it fails."""
    result = subprocess.run(["git", *args], capture_output=True, text=True, input=stdin)
    return result.stdout if result.returncode == 0 else None


def full_sha(sha: str) -> str | None:
    """The full commit id of a sha, or None when it names no commit here."""
    if not HEAD_SHA.fullmatch(sha):
        return None
    out = git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return out.strip() if out else None


def patch_id(sha: str, base: str) -> str | None:
    """`git patch-id --stable` of the change from where sha left base to sha; None for no change or no commit."""
    fork = git("merge-base", base, sha)
    diff = git("diff", "--no-ext-diff", "--no-color", "--binary", fork.strip(), sha) if fork else None
    out = git("patch-id", "--stable", stdin=diff) if diff else None
    return out.split()[0] if out and out.strip() else None


def cell(value: str) -> str:
    """One ledger cell: no tab or line break, and no leading formula character."""
    flat = CELL_BREAKS.sub(" ", value)
    return "'" + flat if flat.startswith(FORMULA_START) else flat


def append_row(ledger: Path, row: tuple[str, ...]) -> None:
    """Append one row under the ledger's lock, writing the column names first into a new ledger."""
    with locked(ledger):
        is_new = not ledger.exists() or ledger.stat().st_size == 0
        with open(ledger, "a", encoding="utf-8") as handle:
            if is_new:
                handle.write("\t".join(LEDGER_COLUMNS) + "\n")
            handle.write("\t".join(cell(value) for value in row) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def cmd_verdict(ledger: Path, args: list[str]) -> None:
    level, evidence = option(args, "--level"), option(args, "--evidence")
    if len(args) != 4 or level is None or evidence is None:
        raise SystemExit("verdict needs <ID> <reviewer> <sha> <pass|fail> --level <level> --evidence <path>")
    sid, reviewer, sha, verdict = args
    if not STORY_ID.fullmatch(sid):
        raise SystemExit(f"story ID {sid!r}: an ID has only letters, digits, '-' and '_'")
    if not REVIEWER_NAME.fullmatch(reviewer):
        raise SystemExit(f"reviewer {reviewer!r}: a reviewer name has only letters, digits, '-', '_' and ':'")
    if verdict not in VERDICTS:
        raise SystemExit(f"verdict {verdict!r}: one of {', '.join(VERDICTS)}")
    if level not in LEVELS:
        raise SystemExit(f"--level {level!r}: one of {', '.join(LEVELS)}")
    if verdict == "pass" and level in NOT_A_PASS:
        raise SystemExit(f"a pass can't be {level}: record it as fail")
    commit = full_sha(sha)
    if commit is None:
        raise SystemExit(f"{sha!r} isn't a commit in this repo")
    append_row(ledger, (now(), sid, reviewer, commit, verdict, level, evidence))
    print(f"Recorded {sid}: {reviewer} {verdict} ({level}) on {commit[:12]}.")


def ledger_rows(ledger: Path, sid: str) -> list[dict[str, str]]:
    """The story's rows, oldest first. A row with the wrong number of cells is reported and skipped."""
    if not ledger.exists():
        return []
    rows = []
    for number, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), start=1):
        cells = line.split("\t")
        if len(cells) != len(LEDGER_COLUMNS):
            print(f"{ledger}:{number}: skipped, not {len(LEDGER_COLUMNS)} cells", file=sys.stderr)
            continue
        row = dict(zip(LEDGER_COLUMNS, cells))
        if row["story"] == sid and row["ts"] != "ts":
            rows.append(row)
    return rows


def base_branch() -> str:
    """foreman.json's base_branch, or main."""
    try:
        config = json.loads((main_checkout() / ".claude" / "foreman.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_BASE
    value = config.get("base_branch") if isinstance(config, dict) else None
    return value if isinstance(value, str) and value else DEFAULT_BASE


def missing_pass(rows: list[dict[str, str]], name: str, matches: dict[str, bool]) -> str | None:
    """None when the reviewer's latest row on a matching sha is a pass, else what is missing."""
    mine = [row for row in rows if row["reviewer"] == name and matches[row["sha"]]]
    if not mine:
        return f"{name}: no verdict on this head or on an earlier sha with the same patch-id"
    last = mine[-1]
    if last["verdict"] != "pass":
        return f"{name}: latest verdict is {last['verdict']} ({last['level']}) on {last['sha'][:12]}"
    return None


def cmd_verdicts(ledger: Path, sid: str, args: list[str]) -> None:
    head, names, base = option(args, "--head"), option(args, "--reviewers"), option(args, "--base")
    if args or head is None or names is None:
        raise SystemExit("verdicts needs <ID> --head <sha> --reviewers a,b,c [--base REF]")
    reviewers = [name.strip() for name in names.split(",") if name.strip()]
    if not reviewers:
        raise SystemExit("--reviewers needs at least one name")
    commit = full_sha(head)
    if commit is None:
        raise SystemExit(f"--head {head!r} isn't a commit in this repo")
    rows = ledger_rows(ledger, sid)
    base = base or base_branch()
    head_id = patch_id(commit, base)
    matches = {sha: sha == commit or (head_id is not None and patch_id(sha, base) == head_id)
               for sha in {row["sha"] for row in rows}}
    missing = [problem for problem in (missing_pass(rows, name, matches) for name in reviewers) if problem]
    if missing:
        print(f"{sid}: not every reviewer passed {commit[:12]}:", file=sys.stderr)
        for problem in missing:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(CONTRACT_BROKEN)
    print(f"{sid}: {', '.join(reviewers)} passed {commit[:12]}.")


def main(argv: list[str]) -> None:
    args = list(argv)
    registry = option(args, "--registry")
    transcripts = Path(option(args, "--transcripts") or Path.home() / ".claude" / "projects")
    handoffs_dir = option(args, "--handoffs")
    ledger_file = option(args, "--ledger")
    if not args:
        raise SystemExit(__doc__)
    command, rest = args[0], args[1:]
    if command in ("verdict", "verdicts"):
        ledger = Path(ledger_file) if ledger_file else main_checkout() / LEDGER_NAME
        if command == "verdict":
            cmd_verdict(ledger, rest)
        elif not rest:
            raise SystemExit("verdicts needs a story ID")
        else:
            cmd_verdicts(ledger, rest[0], rest[1:])
        return
    if command in ("report", "handoff-path"):
        if not rest:
            raise SystemExit(f"{command} needs a story ID")
        handoffs = Path(handoffs_dir) if handoffs_dir else main_checkout() / HANDOFFS_NAME
        if command == "report":
            cmd_report(handoffs, rest[0], rest[1:])
            return
        sid, rest = rest[0], rest[1:]
        reviewer = reviewer_args(rest)
        if rest:
            raise SystemExit(f"handoff-path: unexpected {' '.join(rest)}")
        print(handoff_path(handoffs, sid, reviewer))
        return
    path = Path(registry) if registry else main_checkout() / REGISTRY_NAME
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
