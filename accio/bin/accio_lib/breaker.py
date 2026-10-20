"""boggart's script half (S-041): run a repro against a story's head and base, and say what it proves.

A repro is one file the breaker wrote to break the story's code. Each starts with two comment lines, `claim: <text>`
and `source: <DoD id like S-012/3, or file:line>`; a missing or empty one is "no written claim". The config's
`breaker: {"command": "... {file}"}` runs it, in a throwaway worktree at a commit, as checks do; exit code 0 is a
pass. A repro that fails is read from its output:
- a setup error (`ImportError`, `SyntaxError`, a missing fixture or command ...) is not a break: dropped
- an assertion (`AssertionError`, a runner's own assert line), or a traceback naming a file the story changed, is one

Head runs up to twice: a pass, or a failure in only one run, drops the repro. A break that also fails on base is
`pre-existing` (out of scope). `verify` writes `run/<ID>/boggart/verdicts.json`. It judges every repro again, also
those marked `fixed` or `pre-existing` before (an old verdict is never copied); one that now passes is `fixed`.
"""
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile

from accio_lib import checks, merge

REPRO_FOLDER = "repros"
BOGGART_FOLDER = "boggart"
VERDICTS_NAME = "verdicts.json"
LOG_NAME = "log.txt"
IN_WORKTREE = ".accio-repro"  # where a repro is copied inside the throwaway worktree
RUN_TIMEOUT_SECONDS = 120
HEAD_RUNS = 2
CLAIM_SCAN_LINES = 10
KEPT, DROPPED, PRE_EXISTING, FIXED = "kept", "dropped", "pre-existing", "fixed"
PASSED_ON_HEAD = "passed on head"
FAILED_ONCE = "failed on head in only 1 of 2 runs"
SETUP_ERROR = re.compile(r"ImportError|ModuleNotFoundError|SyntaxError|IndentationError|fixture '[^']*' not found"
                         r"|command not found")
ASSERTION = re.compile(r"AssertionError|^FAIL\b|^not ok\b|Assertion failed|^E\s+assert\b", re.MULTILINE)
COMMENT_FIELD = r"^\s*(?:#+|//+|--|;+|/\*+|\*)\s*{name}:[ \t]*(?P<value>.*?)\s*(?:\*/)?\s*$"


class BreakerError(Exception):
    """A breaker problem, written for the user."""


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BreakerError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def read_field(text, name):
    """The value of a `<name>: ...` comment line in a repro's first lines; "" when missing or empty."""
    pattern = re.compile(COMMENT_FIELD.format(name=name), re.IGNORECASE)
    for line in text.splitlines()[:CLAIM_SCAN_LINES]:
        match = pattern.match(line)
        if match:
            return match["value"].strip()
    return ""


def _run_at(worktree, commit, repro, command):
    """(passed, output) of the command on the repro copied into a throwaway worktree at `commit`."""
    holder = pathlib.Path(tempfile.mkdtemp(prefix="accio-break-")).resolve()
    throwaway = holder / "wt"
    try:
        _git(worktree, "worktree", "add", "-q", "--detach", str(throwaway), commit)
        target = throwaway / IN_WORKTREE / repro.name
        target.parent.mkdir(parents=True)
        shutil.copy2(repro, target)
        line = command.replace("{file}", shlex.quote(f"{IN_WORKTREE}/{repro.name}"))
        passed, output = merge.run_command(throwaway, line, RUN_TIMEOUT_SECONDS, keep_all=True)
        return passed, output.replace(f"{throwaway}/", "")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(throwaway)], cwd=worktree, capture_output=True,
                       check=False)
        shutil.rmtree(holder, ignore_errors=True)


def _names_changed_file(output, changed):
    for path in changed:
        pattern = re.compile(rf'(?:File "|(?<![\w.-])){re.escape(path)}(?:"|:\d+)')
        if pattern.search(output.replace("\\", "/")):
            return path
    return None


def _kind(outputs, changed):
    """(kind, why) for failing head outputs: "assertion", "crash" or "setup"/"other" (not a break)."""
    joined = "\n".join(outputs)
    setup = SETUP_ERROR.search(joined)
    if setup:
        return "setup", f"failed with a setup error ({setup.group(0)}), not a break"
    if ASSERTION.search(joined):
        return "assertion", "failed an assertion on head in both runs"
    crashed = _names_changed_file(joined, changed)
    if crashed:
        return "crash", f"crashed in {crashed} on head in both runs"
    return "other", "failed, but neither an assertion nor a crash in a changed file"


def _entry(repro, verdict, reason):
    text = repro.read_text(encoding="utf-8", errors="replace")
    return {"file": repro.name, "verdict": verdict, "reason": reason, "claim": read_field(text, "claim"),
            "source": read_field(text, "source")}


def judge(worktree, repro, command, head, base, changed):
    """The verdict entry for one repro (S-041/1 to /7)."""
    outputs = []
    for _ in range(HEAD_RUNS):
        passed, output = _run_at(worktree, head, repro, command)
        if passed:
            return _entry(repro, DROPPED, FAILED_ONCE if outputs else PASSED_ON_HEAD)
        outputs.append(output)
    kind, why = _kind(outputs, changed)
    if kind in ("setup", "other"):
        return _entry(repro, DROPPED, why)
    if not _run_at(worktree, base, repro, command)[0]:
        return _entry(repro, PRE_EXISTING, "fails on base too: out of scope")
    entry = _entry(repro, KEPT, why)
    if not entry["claim"] or not entry["source"]:
        return {**entry, "verdict": DROPPED, "reason": "no written claim quoted with its source"}
    return entry


def _rerun(worktree, repro, command, head, base, changed, earlier):
    """A repro judged before, judged again on the code as it is now; the old verdict is never copied (S-052).
    A `kept` or `fixed` repro that passes on head is `fixed`; one that fails twice is `kept` again; one that fails
    only once keeps its earlier verdict. A `pre-existing` one is judged from scratch, base included."""
    entry = judge(worktree, repro, command, head, base, changed)
    if earlier["verdict"] == PRE_EXISTING:
        return entry
    if entry["verdict"] == DROPPED and entry["reason"] == PASSED_ON_HEAD:
        return {**earlier, "verdict": FIXED, "reason": "passes on head after the fix round"}
    if entry["verdict"] == DROPPED and entry["reason"] == FAILED_ONCE:
        return earlier
    # failed twice on head, whatever the cause: only a clean pass may change a kept or fixed verdict
    return {**earlier, "verdict": KEPT, "reason": f"still fails on head: {entry['reason']}"}


def _with_scope(entry, dod_ids):
    return {**entry, "in_dod": entry["source"] in dod_ids}


def _context(worktree, run_dir, settings):
    head = _git(worktree, "rev-parse", "HEAD")
    base = checks.diff_start(run_dir, worktree, settings["base_branch"])
    return head, base, checks.changed_files(worktree, base)


def _log(run_dir, line):
    folder = pathlib.Path(run_dir) / BOGGART_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / LOG_NAME).open("a", encoding="utf-8") as log:
        log.write(line + "\n")


def _skipped(run_dir, story_id):
    reason = "config.json has no `breaker` command, so no repro was run"
    _log(run_dir, f"{story_id} skipped: {reason}")
    return {"skipped": True, "reason": reason, "repros": []}


def try_repro(worktree, run_dir, settings, dod_ids, file):
    """Judge one repro file now, and keep a copy in run/<ID>/boggart/repros/ for `verify`."""
    story_id = pathlib.Path(run_dir).name
    if not settings.get("breaker"):
        return _skipped(run_dir, story_id)
    source = pathlib.Path(file)
    if not source.is_file():
        raise BreakerError(f"{file} is not a file")
    folder = pathlib.Path(run_dir) / BOGGART_FOLDER / REPRO_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    repro = folder / source.name
    if source.resolve() != repro.resolve():
        shutil.copy2(source, repro)
    head, base, changed = _context(worktree, run_dir, settings)
    return {"skipped": False, "repros": [_with_scope(judge(worktree, repro, settings["breaker"]["command"], head,
                                                           base, changed), dod_ids)]}


def _earlier_verdicts(path):
    try:
        return {entry["file"]: entry for entry in json.loads(path.read_text(encoding="utf-8"))["repros"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def verify(worktree, run_dir, settings, dod_ids):
    """Judge every repro in run/<ID>/boggart/repros/ and write verdicts.json; reruns the ones kept before."""
    story_id = pathlib.Path(run_dir).name
    if not settings.get("breaker"):
        return _skipped(run_dir, story_id)
    command = settings["breaker"]["command"]
    verdicts = pathlib.Path(run_dir) / BOGGART_FOLDER / VERDICTS_NAME
    earlier = _earlier_verdicts(verdicts)
    head, base, changed = _context(worktree, run_dir, settings)
    entries = []
    for repro in sorted((pathlib.Path(run_dir) / BOGGART_FOLDER / REPRO_FOLDER).glob("*")):
        before = earlier.get(repro.name)
        if before and before["verdict"] in (KEPT, FIXED, PRE_EXISTING):
            entry = _rerun(worktree, repro, command, head, base, changed, before)
        else:
            entry = judge(worktree, repro, command, head, base, changed)
        entries.append(_with_scope(entry, dod_ids))
    verdicts.parent.mkdir(parents=True, exist_ok=True)
    verdicts.write_text(json.dumps({"repros": entries}, indent=2) + "\n", encoding="utf-8")
    return {"skipped": False, "repros": entries}


def dod_ids_of(parsed_story):
    return frozenset(line.id for line in parsed_story.dod)
