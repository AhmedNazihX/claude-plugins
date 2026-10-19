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
  `allow-once.json` (owl's grants for one build), which nothing writes during a story. Times are recorded with `ctime`, which can't be set back.
  Paths matching config's `snapshot_skip` globs (another tool's files, such as `.remember/**`) are left out of the
  comparison; accio's own run files never are.
  **Limit:** the snapshot file lives in `.accio/run/` too, so code the story runs could rewrite it; like curfew
  (DESIGN § 6), this catches mistakes and leaves a trail, not a determined agent.
- **diff start:** the base `accio-brief` recorded for the story (its parent's head when stacked), when it is a full
  commit id and an ancestor of the story's HEAD; never a caller's choice, and the same one `accio-ledger key` uses;
  the merge-base with the base branch otherwise.
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
import re
import shlex
import subprocess
import time

from accio_lib import brief, globs, merge

TEST_FOLDERS = frozenset({"test", "tests", "__tests__", "spec", "specs", "__snapshots__", "testdata", "fixtures",
                          "e2e", "cypress"})
TEST_FOLDER_NAME = re.compile(r"^.+Tests$")  # Xcode's AppTests/
TEST_STEMS = (re.compile(r"^test_.+"), re.compile(r"^.+_(test|spec)$"), re.compile(r"^.+\.(test|spec|cy)$"),
              re.compile(r"^tests?$"), re.compile(r"^.+Tests?$"), re.compile(r"^conftest$"))
CODE_EXTENSIONS = frozenset({"py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "rb", "java", "kt", "kts",
                             "swift", "cs", "php", "scala", "ex", "exs", "c", "cc", "cpp", "cxx", "h", "hpp", "m",
                             "mm", "dart", "lua", "clj", "hs", "ml", "fs", "r", "jl", "sh", "bash", "bats", "zsh"})
DATA_EXTENSIONS = frozenset({"json", "yaml", "yml", "toml", "csv", "tsv", "txt", "xml", "html", "md", "snap", "plist",
                             "golden", "ini", "cfg", "png", "jpg", "jpeg", "gif", "svg", "pdf"})  # fixtures
RUN_FOLDER = ".accio/run/"
WATCHED_RUN_FILES = ("push-ok", "*/base", "allow-once.json")  # nothing writes these during a story
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
    is_fixture = _in_test_folder(parts) and parts[-1].rpartition(".")[2].lower() in DATA_EXTENSIONS
    return not _under_dot_folder(parts) and (is_fixture or is_test_file(path))


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


def trusted_base(run_dir, worktree):
    """The base accio-brief recorded, when it is a full commit id and an ancestor of the story's HEAD; else None
    (the run folder is reachable from code the story runs, so the record is checked, not trusted)."""
    recorded = brief.recorded_base(run_dir)
    if not recorded or not COMMIT_ID.fullmatch(recorded):
        return None
    result = subprocess.run(["git", "merge-base", "--is-ancestor", recorded, "HEAD"], cwd=worktree,
                            capture_output=True, check=False)
    return recorded if result.returncode == 0 else None


def diff_start(run_dir, worktree, base_branch):
    """Where the story's diff starts: the trusted recorded base, else the merge-base with the base branch."""
    return trusted_base(run_dir, worktree) or _git(worktree, "merge-base", base_branch, "HEAD").decode().strip()


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


def snapshot(main, base_branch):
    dirty = {path: _record(main, code, path) for code, path in merge.status_entries(main)
             if not path.startswith(RUN_FOLDER) and path != RUN_FOLDER.rstrip("/")}
    return {"head": _ref(main, "HEAD"), "dirty": {**dirty, **_watched_run_files(main)}, "git": _git_state(main),
            "origin": _ref(main, f"refs/remotes/origin/{base_branch}")}


def _skipped(path, skip):
    """Whether config's `snapshot_skip` covers `path`; accio's own run files are always watched."""
    return not path.startswith(RUN_FOLDER) and globs.matches_any(path, skip)


def compare(before, after, skip=()):
    """(paths that changed in the main checkout, `HEAD` for a commit; whether origin/<base> moved).

    `skip` holds config's `snapshot_skip` globs: paths another tool keeps writing during a run.
    """
    paths = sorted(path for path in set(before["dirty"]) | set(after["dirty"])
                   if before["dirty"].get(path) != after["dirty"].get(path) and not _skipped(path, skip))
    moved_head = ["HEAD"] if before["head"] != after["head"] else []
    git_state = [name for name in sorted(after.get("git", {}))
                 if before.get("git", {}).get(name) != after["git"][name]]
    return moved_head + git_state + paths, before["origin"] != after["origin"]


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


def run(main, worktree, parsed_story, start, settings, before, run_dir):
    """prefect's reply (DESIGN § 12.5) for a story's worktree, its diff start and the snapshot taken before it."""
    deadline = time.monotonic() + CHECK_TIMEOUT_SECONDS
    changed = changed_files(worktree, start)
    failing = sorted(_run_within_budget(worktree, scoped_to_diff(settings["checks"], changed), deadline))
    audited, weak_tests, audit_output = audit(worktree, start, run_dir, settings.get("mutation"), deadline)
    main_changed, remote_moved = compare(before, snapshot(main, settings["base_branch"]),
                                         settings.get("snapshot_skip", ()))
    reply = {"failing": failing, "skipped": False,
             "out_of_bounds": out_of_bounds(changed, parsed_story.meta.get("files", ())),
             "untagged": untagged(parsed_story.dod, test_texts(worktree)), "weak_tests": weak_tests,
             "audit": audited, "audit_output": audit_output, "main_changed": main_changed,
             "remote_moved": remote_moved}
    passed = not (failing or reply["out_of_bounds"] or reply["untagged"] or weak_tests or main_changed
                  or remote_moved)
    return {"pass": passed, **reply}
