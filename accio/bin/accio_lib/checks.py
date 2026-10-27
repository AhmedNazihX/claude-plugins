"""prefect's check script (DESIGN § 3.4 step 3, § 7.1, § 12.5; decisions 009, 011).

Scripts, not a model, decide these, so an agent's claim never does:
- **scoped checks:** only the configured checks whose glob matches a changed file run (`merge.run_checks`, with
  its process-group kill), all within one CHECK_TIMEOUT_SECONDS budget: prefect runs this through a Bash tool call
  of at most 10 min
- **boundary:** a changed file outside the story's `files` is `out_of_bounds`, unless it is in a test area: a test
  code file (in a test folder such as `tests/`, `__tests__/`, `testdata/`, `AppTests/`, or named like `test_a.py`,
  `a_test.go`, `a.spec.ts`, `login.cy.ts`, `FooTests.swift`, `conftest.py`, Django's `tests.py`), or a data file (a
  fixture) in a test folder. Nothing under a dot-folder (`.github/`, `.husky/`, `.accio/` …) is ever a test.
- **DoD tags:** a numbered DoD line not marked `(no test)` whose tag appears in no test *code* file of the worktree
  (fixtures don't count; shell and bats tests do) is `untagged`; a tag is written `S-001/3` or `S_001_3`, never
  followed by another digit
- **main snapshot:** `snapshot` records the main checkout once per brief (`accio-brief` clears it; a second one
  needs `--fresh`, which only `portkey` may ask for): HEAD, `origin/<base>`, and each changed, untracked or ignored
  path with its status code and mode, plus its content hash (tracked and untracked files up to MAX_HASHED_BYTES),
  its size and change time (ignored or bigger files), a listing of the files inside (an ignored folder, up to
  MAX_LISTED_FILES) or its target (a symlink). After the story, any difference is `main_changed` (`HEAD` for a
  commit; `git refs`, `git config` or `git hooks` when those change), and a moved `origin/<base>` is
  `remote_moved`. `.accio/run/` is left out, since the run writes there, except `push-ok`, each story's `base` and
  `parent-heads`, and `allow-once.json` (owl's grants for one build), which nothing writes during a story; another
  story's base and pins, written when a parallel build prepares it, count only when the base-writes log lacks them. Times are recorded with `ctime`, which can't be set back.
  Paths matching config's `snapshot_skip` globs (another tool's files, such as `.remember/**`) are left out of the
  comparison; nothing under `.accio/` ever is (the skip list itself lives there). Finder's `.DS_Store` files never
  count, anywhere.
  **Limit:** the snapshot file lives in `.accio/run/` too, so code the story runs could rewrite it; like curfew
  (DESIGN § 6), this catches mistakes and leaves a trail, not a determined agent.
- **diff start:** the base `accio-brief` recorded for the story (its parent's head when stacked), when it is a full
  commit id, an ancestor of the story's HEAD, and either a parent head `accio-brief` pinned beside it (S-074) or an
  ancestor of the base branch (so never a commit only the story's own branch has, S-072, and never one a moved
  parent branch points at); never a caller's choice, and the same one `accio-ledger key` uses; the merge-base with
  the base branch otherwise.
- **test audit (decision 011, option A):** with `mutation.command` in config.json, the story's diff goes to
  `run/<ID>/story.diff` and the command runs in the worktree with `{diff}` replaced by that file's path, within what
  is left of the time budget. The tool mutates only the changed lines (natively, like `cargo mutants --in-diff`, or
  through a small wrapper) and prints each mutant that no test caught on its own line, starting `file:line`; those
  lines are `weak_tests` and fail the story. No command: "not audited". A command that fails or runs out of time:
  "failed", reported with its output, and the story isn't failed for it (a broken tool mustn't block every build).
"""
import hashlib
import os
import pathlib
import posixpath
import re
import shlex
import subprocess
import time

from accio_lib import brief, globs, merge

TEST_FOLDERS = frozenset({"test", "tests", "__tests__", "spec", "specs", "__snapshots__", "testdata", "fixtures",
                          "e2e", "cypress"})
EVAL_FOLDERS = frozenset({"evals", "eval", "__mocks__", "__fixtures__"})  # part of a story's test area (S-035/4)
TEST_FOLDER_NAME =re.compile(r"^.+Tests$")  # Xcode's AppTests/
TEST_STEMS = (re.compile(r"^test_.+"), re.compile(r"^.+_(test|spec)$"), re.compile(r"^.+\.(test|spec|cy)$"),
              re.compile(r"^tests?$"), re.compile(r"^.+Tests?$"), re.compile(r"^conftest$"))
CODE_EXTENSIONS = frozenset({"py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "rb", "java", "kt", "kts",
                             "swift", "cs", "php", "scala", "ex", "exs", "c", "cc", "cpp", "cxx", "h", "hpp", "m",
                             "mm", "dart", "lua", "clj", "hs", "ml", "fs", "r", "jl", "sh", "bash", "bats", "zsh"})
DATA_EXTENSIONS = frozenset({"json", "yaml", "yml", "toml", "csv", "tsv", "txt", "xml", "html", "md", "snap", "plist",
                             "golden", "ini", "cfg", "png", "jpg", "jpeg", "gif", "svg", "pdf"})  # fixtures
ACCIO_FOLDER = ".accio"
OS_FILES = frozenset({".DS_Store"})  # macOS Finder writes these whenever a folder is opened
PLAYWRIGHT_FOLDER = ".playwright-mcp"  # the Playwright MCP server logs pages and console here on every session
RUN_FOLDER = ".accio/run/"
BASE_NAME = brief.BASE_RECORD
PINS_NAME = brief.PARENT_HEADS
WATCHED_RUN_FILES = ("push-ok", f"*/{BASE_NAME}", f"*/{PINS_NAME}", "allow-once.json")  # nothing writes these during
# a story, except another story's base and pins in a parallel build (see `compare`)
BASE_WRITES_LOG = "base-writes.log"  # `accio-brief` appends `<ID> <full sha>` per base and `<ID> <dep> <full sha>`
# per pinned parent head it writes; only appends are fine
COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
STORY_REFS = b"refs/heads/story/"  # story branches move with every checkpoint commit
SNAPSHOT_NAME = "main-snapshot.json"
CHECK_TIMEOUT_SECONDS = 9 * 60  # for all of a story's checks together
MAX_TEST_BYTES = 1_000_000
MAX_HASHED_BYTES = 50_000_000  # a bigger file is recorded by size and change time
MAX_LISTED_FILES = 20_000      # an ignored folder with more files counts by its presence only
NOT_AUDITED = "not audited"
AUDITED = "audited"
AUDIT_FAILED = "failed"
SURVIVOR = re.compile(r"^\S+:\d+(?:\D|$)")
DIFF_NAME = "story.diff"
FINDINGS_NAME = "check-findings.md"
FINDING_HEADING = re.compile(r"^## (?P<id>check-\d+) \[(?:open|resolved)\] (?P<title>.+)$", re.MULTILINE)


class CheckError(Exception):
    """A check that can't run, written for the user."""


def _git(cwd, *args):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except OSError as error:
        raise CheckError(f"git could not run in {cwd}: {error}") from error
    if result.returncode != 0:
        raise CheckError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


# --- tests and the boundary --------------------------------------------------------------------------------------

def _parts(path):
    return pathlib.PurePosixPath(path).parts


def _under_dot_folder(parts):
    return any(part.startswith(".") for part in parts[:-1])


def _in_test_folder(parts):
    return any(part.lower() in TEST_FOLDERS or TEST_FOLDER_NAME.match(part) for part in parts[:-1])


def is_test_file(path):
    """A test code file: code, not under a dot-folder, and in a test folder or named like a test."""
    parts = _parts(path)
    stem, _, extension = parts[-1].rpartition(".")
    if _under_dot_folder(parts) or extension.lower() not in CODE_EXTENSIONS or not stem:
        return False
    return _in_test_folder(parts) or any(pattern.match(stem) for pattern in TEST_STEMS)


def in_test_area(path):
    """A test file, or a data file (a fixture) in a test folder; never under a dot-folder."""
    parts = _parts(path)
    if _under_dot_folder(parts):
        return False
    if any(part.lower() in EVAL_FOLDERS for part in parts[:-1]):
        return True  # evals, mocks and fixtures: whatever the file is
    is_fixture = _in_test_folder(parts) and parts[-1].rpartition(".")[2].lower() in DATA_EXTENSIONS
    return is_fixture or is_test_file(path)


def scoped_to_diff(configured, changed):
    """The check commands whose glob matches a changed file, in config order."""
    return tuple(check["command"] for check in configured
                 if any(globs.match(path, check["glob"]) for path in changed))


def out_of_bounds(changed, story_files):
    """Changed files the story doesn't list and that aren't in a test area, in diff order."""
    return [path for path in changed if not in_test_area(path) and not globs.matches_any(path, story_files)]


def _tag_patterns(dod_id):
    underscored = dod_id.replace("-", "_").replace("/", "_")
    return [re.compile(rf"(?<![A-Za-z0-9]){re.escape(form)}(?!\d)") for form in (dod_id, underscored)]


def untagged(dod, test_texts):
    """Numbered, testable DoD lines whose tag no test text carries."""
    joined = "\n".join(test_texts)
    return [line.id for line in dod
            if line.testable and not any(pattern.search(joined) for pattern in _tag_patterns(line.id))]


def drift(stories, status, root):
    """Done stories whose testable DoD lines no test in `root` carries any more: [{id, title, lines}], by id."""
    done = [sid for sid in sorted(stories) if status[sid] == "done"]
    if not done:
        return []
    texts = test_texts(root)
    lost = [(sid, untagged(stories[sid].dod, texts)) for sid in done]
    return [{"id": sid, "title": stories[sid].meta["title"], "lines": lines} for sid, lines in lost if lines]


def changed_files(worktree, start):
    return [path for path in _git(worktree, "diff", "--name-only", "-z", "--no-renames", start, "HEAD")
            .decode("utf-8", errors="replace").split("\0") if path]


def test_texts(worktree):
    texts = []
    for path in _git(worktree, "ls-files", "-z").decode("utf-8", errors="replace").split("\0"):
        file = pathlib.Path(worktree) / path
        if path and is_test_file(path) and file.is_file() and file.stat().st_size <= MAX_TEST_BYTES:
            texts.append(file.read_text(encoding="utf-8", errors="replace"))
    return texts


def _is_ancestor(worktree, commit, rev):
    result = subprocess.run(["git", "merge-base", "--is-ancestor", commit, rev], cwd=worktree,
                            capture_output=True, check=False)
    return result.returncode == 0


def trusted_base(run_dir, worktree, base_branch):
    """The base accio-brief recorded, when it is a full commit id, an ancestor of the story's HEAD, and either one of
    the parent heads accio-brief pinned beside it (a stacked story, S-074) or an ancestor of the base branch; else
    None.

    The run folder is reachable from code the story runs, so the record is checked, not trusted. Being an ancestor of
    HEAD alone isn't enough: HEAD, or any commit the story made, is one too, and would shorten the diff (S-072). A
    parent's live `story/<dep>` branch isn't asked either: story branches aren't watched by the main snapshot, so the
    story's code could move one onto its own commit; the pin is the parent's head as accio-brief saw it, and it still
    holds after the parent's branch moves on. The main snapshot lists a write to `run/<ID>/base` or
    `run/<ID>/parent-heads`, but only up to `accio-check`, and its own file lives in the run folder too. Limit: code
    that moves the base branch still passes this check (that shows in the snapshot's `git refs`)."""
    recorded = brief.recorded_base(run_dir)
    if not recorded or not COMMIT_ID.fullmatch(recorded) or not _is_ancestor(worktree, recorded, "HEAD"):
        return None
    if recorded in brief.pinned_heads(run_dir) or _is_ancestor(worktree, recorded, base_branch):
        return recorded
    return None


def diff_start(run_dir, worktree, base_branch):
    """Where the story's diff starts: the trusted recorded base, else the merge-base with the base branch."""
    return (trusted_base(run_dir, worktree, base_branch)
            or _git(worktree, "merge-base", base_branch, "HEAD").decode().strip())


# --- the main checkout ---------------------------------------------------------------------------------------------

def _stat_line(stat):
    """Size, change and status-change time: `ctime` can't be set back the way `mtime` can (`touch -d`)."""
    return f"{stat.st_size}|{stat.st_mtime_ns}|{stat.st_ctime_ns}"


def _folder_listing(folder):
    """A hash of every file under an (ignored) folder by path, size and change time; "many files" past the cap."""
    rows = []
    for root, _, names in os.walk(folder):
        for name in names:
            stat = os.lstat(os.path.join(root, name))
            rows.append(f"{os.path.relpath(os.path.join(root, name), folder)}|{_stat_line(stat)}")
            if len(rows) > MAX_LISTED_FILES:
                return "many files"
    return hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()


def _content(file, stat, ignored):
    if os.path.islink(file):
        return f"link:{os.readlink(file)}"
    if file.is_dir():
        return _folder_listing(file)
    if ignored or stat.st_size > MAX_HASHED_BYTES:
        return _stat_line(stat)
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _record(main, code, path):
    """What a path looks like: its status code, mode and content (ignored files by size and change time)."""
    file = pathlib.Path(main) / path
    try:
        stat = os.lstat(file)
        return f"{code}|{oct(stat.st_mode)}|{_content(file, stat, code == '!!')}"
    except OSError:
        return f"{code}|-|missing"


def _ref(main, ref):
    try:
        return _git(main, "rev-parse", "--verify", "-q", ref).decode().strip() or None
    except CheckError:
        return None


def _git_state(main):
    """Hashes of what git itself runs or trusts: every ref but the story branches, the config, the hooks folder."""
    common = pathlib.Path(_git(main, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    hooks = pathlib.Path(_git(main, "rev-parse", "--path-format=absolute", "--git-path", "hooks").decode().strip())
    config = common / "config"
    refs = [line for line in _git(main, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
            if not line.startswith(STORY_REFS)]
    return {"git refs": hashlib.sha256(b"\n".join(refs)).hexdigest(),
            "git config": hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else "missing",
            "git hooks": _folder_listing(hooks) if hooks.is_dir() else "missing"}


def _watched_run_files(main):
    run = pathlib.Path(main) / RUN_FOLDER
    found = [path for pattern in WATCHED_RUN_FILES for path in run.glob(pattern)]
    return {str(path.relative_to(main)): _record(main, "run", str(path.relative_to(main))) for path in found}


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _run_contents(main, name):
    """Each story's `run/<ID>/<name>` content, so a forgiven change can be matched to the log."""
    run = pathlib.Path(main) / RUN_FOLDER
    return {path.parent.name: _read_text(path).strip() for path in run.glob(f"*/{name}") if path.is_file()}


def snapshot(main, base_branch):
    dirty = {path: _record(main, code, path) for code, path in merge.status_entries(main)
             if not path.startswith(RUN_FOLDER) and path != RUN_FOLDER.rstrip("/")}
    return {"head": _ref(main, "HEAD"), "dirty": {**dirty, **_watched_run_files(main)}, "git": _git_state(main),
            "bases": _run_contents(main, BASE_NAME), "pins": _run_contents(main, PINS_NAME),
            "base writes": _read_text(pathlib.Path(main) / RUN_FOLDER / BASE_WRITES_LOG),
            "origin": _ref(main, f"refs/remotes/origin/{base_branch}")}


def _skipped(path, skip):
    """Whether config's `snapshot_skip` covers `path`; accio's own files (`.accio/`) are always watched.

    `dir/**` also covers `dir` itself: git lists a folder ignored as a whole as one entry. The operating system's
    own files (`OS_FILES`, e.g. Finder's `.DS_Store`) never count, wherever they are.
    """
    if posixpath.basename(path) in OS_FILES:
        return True
    if path == ACCIO_FOLDER or path.startswith(f"{ACCIO_FOLDER}/"):
        return False
    if path == PLAYWRIGHT_FOLDER or path.startswith(f"{PLAYWRIGHT_FOLDER}/"):
        return True
    folders = tuple(pattern[:-len("/**")] for pattern in skip if pattern.endswith("/**"))
    return globs.matches_any(path, (*skip, *folders))


def _run_file(path):
    """(story ID, file name) when `path` is a `run/<ID>/base` or `run/<ID>/parent-heads`, else (None, None)."""
    if not path.startswith(RUN_FOLDER):
        return None, None
    folder, _, name = path.removeprefix(RUN_FOLDER).partition("/")
    return (folder, name) if name in (BASE_NAME, PINS_NAME) else (None, None)


def _needed_log_lines(owner, name, after):
    """The log lines that show accio wrote the file's new content: one for a base, one per pin; None when missing."""
    if name == BASE_NAME:
        content = after.get("bases", {}).get(owner)
        return [f"{owner} {content}"] if content else None
    content = after.get("pins", {}).get(owner)
    return None if content is None else [f"{owner} {line.strip()}" for line in content.splitlines() if line.strip()]


def _forgiven_base(path, story_id, after):
    """Whether `path` is another story's base or pins that accio's prepare step wrote: the log has its ID and each
    line of its new content (pins with no parents need none)."""
    owner, name = _run_file(path)
    if story_id is None or owner is None or owner == story_id:
        return False
    needed = _needed_log_lines(owner, name, after)
    logged = set(after.get("base writes", "").splitlines())
    return needed is not None and all(line in logged for line in needed)


def _log_rewritten(before, after):
    """Whether the base-writes log lost or changed a line (lines appended are fine)."""
    return not after.get("base writes", "").startswith(before.get("base writes", ""))


def compare(before, after, skip=(), story_id=None):
    """(paths that changed in the main checkout, `HEAD` for a commit; whether origin/<base> moved).

    `skip` holds config's `snapshot_skip` globs: paths another tool keeps writing during a run. With `story_id`,
    another story's `run/<ID>/base` or `run/<ID>/parent-heads` is forgiven only when the base-writes log holds its new
    content (accio's own prepare wrote it); the log itself counts only when a line was removed or rewritten.
    """
    paths = sorted(path for path in set(before["dirty"]) | set(after["dirty"])
                   if before["dirty"].get(path) != after["dirty"].get(path) and not _skipped(path, skip)
                   and not _forgiven_base(path, story_id, after))
    log = [f"{RUN_FOLDER}{BASE_WRITES_LOG}"] if _log_rewritten(before, after) else []
    moved_head = ["HEAD"] if before["head"] != after["head"] else []
    git_state = [name for name in sorted(after.get("git", {}))
                 if before.get("git", {}).get(name) != after["git"][name]]
    return moved_head + git_state + sorted(paths + log), before["origin"] != after["origin"]


# --- the whole check -----------------------------------------------------------------------------------------------

def _run_within_budget(worktree, commands, deadline):
    """{command: output} for the failing checks, all of them before `deadline`."""
    failing = {}
    for command in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failing[command] = "not run: the checks' time budget ran out"
            continue
        failing.update(merge.run_checks(worktree, [command], timeout=remaining))
    return failing


def audit(worktree, start, run_dir, mutation, deadline):
    """(audit, weak tests, the tool's output when it failed) for the story's diff (decision 011, option A)."""
    if not mutation:
        return NOT_AUDITED, [], ""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return AUDIT_FAILED, [], "not run: the checks' time budget ran out"
    diff_file = pathlib.Path(run_dir) / DIFF_NAME
    diff_file.parent.mkdir(parents=True, exist_ok=True)
    diff_file.write_bytes(_git(worktree, "diff", "--no-color", "--no-ext-diff", "--no-textconv", start, "HEAD"))
    command = mutation["command"].replace("{diff}", shlex.quote(str(diff_file)))
    passed, output = merge.run_command(worktree, command, remaining, keep_all=True)
    if not passed:
        return AUDIT_FAILED, [], output[-merge.OUTPUT_TAIL_CHARS:]
    return AUDITED, [line.strip() for line in output.splitlines() if SURVIVOR.match(line.strip())], ""


def _one_line(text):
    return " ".join(text.split())


def _failures(outputs, bounds, untagged_ids, weak_tests):
    """[(title, detail)] for every finding a check raised: failing commands first, then the scripted checks."""
    tail = merge.OUTPUT_TAIL_CHARS
    return ([(f"failing command: {_one_line(command)}",
              f"Command: `{command}`\n\nLast {tail} characters of its output:\n\n```\n{output[-tail:]}\n```")
             for command, output in sorted(outputs.items())]
            + [(f"untagged DoD line: {tag}", f"No test code file carries the tag {tag}. Add a test and tag it.")
               for tag in untagged_ids]
            + [(f"weak test: {line}", f"A mutant survived: {line}. Strengthen the test so it fails on it.")
               for line in weak_tests]
            + [(f"file outside the story: {path}", f"{path} is not in the story's files. Undo the change.")
               for path in bounds])


def _earlier_findings(path):
    """[(id, title)] from the check-findings file a previous check wrote; [] when there is none."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [(match["id"], match["title"]) for match in FINDING_HEADING.finditer(text)]


def write_findings(run_dir, failures):
    """Write run/<ID>/check-findings.md and return (its path or None, {id: status}).

    A finding keeps its id from one check to the next: one the new check no longer raises is `resolved`, one it
    still raises is `open`, and a new one gets the next id. Nothing is written when nothing failed, now or before."""
    path = pathlib.Path(run_dir) / FINDINGS_NAME
    earlier = _earlier_findings(path)
    ids = {title: finding_id for finding_id, title in earlier}
    next_number = 1 + max((int(finding_id.rsplit("-", 1)[1]) for finding_id, _ in earlier), default=0)
    sections, status = [], {}
    for title, detail in failures:
        if title not in ids:
            ids[title] = f"check-{next_number}"
            next_number += 1
        status[ids[title]] = "open"
        sections.append((ids[title], f"## {ids[title]} [open] {title}\n\n{detail}\n"))
    for finding_id, title in earlier:
        if finding_id not in status:
            status[finding_id] = "resolved"
            sections.append((finding_id, f"## {finding_id} [resolved] {title}\n"))
    if not sections:
        return None, {}
    sections.sort(key=lambda section: int(section[0].rsplit("-", 1)[1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Check findings\n\n" + "\n".join(text for _, text in sections), encoding="utf-8")
    return str(path), status


def run(main, worktree, parsed_story, start, settings, before, run_dir):
    """prefect's reply (DESIGN § 12.5) for a story's worktree, its diff start and the snapshot taken before it."""
    deadline = time.monotonic() + CHECK_TIMEOUT_SECONDS
    changed = changed_files(worktree, start)
    outputs = _run_within_budget(worktree, scoped_to_diff(settings["checks"], changed), deadline)
    audited, weak_tests, audit_output = audit(worktree, start, run_dir, settings.get("mutation"), deadline)
    main_changed, remote_moved = compare(before, snapshot(main, settings["base_branch"]),
                                         settings.get("snapshot_skip", ()), pathlib.Path(run_dir).name)
    bounds = out_of_bounds(changed, parsed_story.meta.get("files", ()))
    missing_tags = untagged(parsed_story.dod, test_texts(worktree))
    reply = {"failing": sorted(outputs), "skipped": False, "out_of_bounds": bounds, "untagged": missing_tags,
             "weak_tests": weak_tests, "audit": audited, "audit_output": audit_output,
             "main_changed": main_changed, "remote_moved": remote_moved}
    findings, check_status = write_findings(run_dir, _failures(outputs, bounds, missing_tags, weak_tests))
    if findings:
        reply.update({"findings": findings, "check_status": check_status})
    passed = not (outputs or bounds or missing_tags or weak_tests or main_changed or remote_moved)
    return {"pass": passed, **reply}
