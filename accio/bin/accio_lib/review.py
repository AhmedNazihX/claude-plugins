"""The review package (DESIGN § 3.4 step 4, § 7.1; S-020): what a story's reviewers read, as files.

- The diff goes to `run/<ID>/review.diff`: the whole story (from where its diff starts, as accio-check takes it) on
  the first review; in a fix round, only the fix, from the commit reviewed last (`--since`), which must be an
  earlier commit of the story.
- `risky` (the workflow adds auror) when the diff under review (the whole story, or a fix round's fix) touches a
  `risky_paths` glob, or the story's `risk` field holds a security word. Paths are read NUL-separated, so a name git
  would quote (a tab, a `"`) still meets the globs as it is. The method checklists follow `references/checklists/README.md`; auror always gets the security one.
"""
import pathlib
import re
import shutil
import subprocess

from accio_lib import breaker, brief, checks, globs

REFERENCES = brief.BIN.parent / "references"
CHECKLISTS = REFERENCES / "checklists"
SECURITY = "auth-and-security.md"
CHECKLIST_WORDS = {
    SECURITY: frozenset({"auth", "security", "secret", "permission", "payment"}),
    "performance.md": frozenset({"performance", "perf", "latency", "scale"}),
    "data-migration.md": frozenset({"migration", "schema", "data"}),
    "accessibility.md": frozenset({"accessibility", "a11y", "ui"}),
}
RISK_WORD_SPLIT = re.compile(r"[\s,\-]+")
DIFF_NAME = "review.diff"
PACKAGE_NAME = "review-package.md"
RULES_FILES = ("CLAUDE.md", ".claude/CLAUDE.md")  # the project's own instructions files, as the base branch holds them
RULES_FOLDER = "project-rules"  # their copies, in run/<ID>/, named in the package (S-084)
REVIEWERS = ("professor", "auror", "examiner")
NON_CODE_SUFFIXES = frozenset({".md", ".mdx", ".txt", ".rst", ".adoc", ".json", ".yaml", ".yml", ".toml", ".ini",
                               ".cfg", ".lock"})  # docs and config: boggart has nothing to break there


def rules_line(main, base, run_dir):
    """The package line naming the project's own instructions files (S-084): each of RULES_FILES as the base branch
    holds it, copied into `run_dir/project-rules/`. The base branch, never a working copy: a story's worktree, or a
    direct fix's branch checked out in the main checkout, must not change the rules it is judged by. No file on the
    base branch: no line."""
    copies = pathlib.Path(run_dir) / RULES_FOLDER
    if copies.exists():
        shutil.rmtree(copies)  # a file the base branch no longer has must not stay named
    found = []
    for name in RULES_FILES:
        text = _at_base(main, base, name)
        if text is None:
            continue
        copy = copies / name
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(text)
        found.append(copy)
    if not found:
        return ""
    names = ", ".join(f"`{path}`" for path in found)
    return (f"\n- The project's rules: {names} (copied from `{base}`; apply them where the change touches them; "
            "accio's rules in your prompt come first)")


def _at_base(main, base, name):
    """The bytes of `name` on the base branch, or None when the branch has no such file."""
    try:
        result = subprocess.run(["git", "cat-file", "blob", f"{base}:{name}"], cwd=main, capture_output=True,
                                check=False)
    except OSError as error:
        raise brief.BriefError(f"git could not run in {main}: {error}") from error
    return result.stdout if result.returncode == 0 else None


def _git(worktree, *args):
    try:
        result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=worktree, capture_output=True,
                                text=True, check=False)
    except OSError as error:
        raise brief.BriefError(f"git could not run in {worktree}: {error}") from error
    if result.returncode != 0:
        raise brief.BriefError(f"git {' '.join(args)} failed in {worktree}: {result.stderr.strip()}")
    return result.stdout


def checklists(risk, touches_risky_path):
    """The checklist file names for a story's `risk` words (matched whole), plus the security one on a risky path."""
    words = set(RISK_WORD_SPLIT.split((risk or "").lower())) - {""}
    picked = [name for name, keys in CHECKLIST_WORDS.items() if words & keys]
    if touches_risky_path and SECURITY not in picked:
        picked.insert(0, SECURITY)
    return tuple(picked)


def _succeeds(worktree, *args):
    try:
        return subprocess.run(["git", *args], cwd=worktree, capture_output=True, check=False).returncode == 0
    except OSError as error:
        raise brief.BriefError(f"git could not run in {worktree}: {error}") from error


def _fix_start(worktree, since, start):
    """`since`, checked: a commit of the story itself, from where it starts up to its HEAD."""
    try:
        commit = _git(worktree, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}").strip()
    except brief.BriefError as error:
        raise brief.BriefError(f"--since {since} is not a commit") from error
    if not (_succeeds(worktree, "merge-base", "--is-ancestor", commit, "HEAD")
            and _succeeds(worktree, "merge-base", "--is-ancestor", start, commit)):
        raise brief.BriefError(f"--since {since} is not a commit of this story, between where it starts and its HEAD")
    return commit


def package(accio, parsed, worktree, settings, since=None):
    """Write the diff and the package; return {package, diff, head, risky, code, breaker, ui, preview, test_data}."""
    story_id = parsed.meta["id"]
    run_dir = accio / "run" / story_id
    head = _git(worktree, "rev-parse", "HEAD").strip()
    try:
        start = checks.diff_start(run_dir, worktree, settings["base_branch"])
    except checks.CheckError as error:
        raise brief.BriefError(f"can't tell where {story_id}'s diff starts: {error}") from error
    origin = _fix_start(worktree, since, start) if since else start
    facts = _diff_facts(worktree, run_dir, origin, head, settings, parsed.meta.get("risk"))
    text = _render(parsed, accio, worktree, {
        **facts, "is_fix": bool(since), "findings": run_dir / "<reviewer>-findings.md",
        "rules_line": rules_line(accio.parent, settings["base_branch"], run_dir)})
    reply = _write(run_dir, text, facts)
    if not since:
        _log_skip(run_dir, story_id, reply)
    return reply


def has_code(paths):
    """True when any changed path is not docs or config (S-043/1); no changed path is no code."""
    return any(pathlib.PurePosixPath(path).suffix.lower() not in NON_CODE_SUFFIXES for path in paths)


def _log_skip(run_dir, story_id, reply):
    """Say in run/<ID>/boggart/log.txt why boggart will not run on this story (S-043/5)."""
    reasons = [text for skipped, text in ((not reply["code"], "the diff has no code (docs or config only)"),
                                          (not reply["breaker"], "config.json has no `breaker` command")) if skipped]
    if not reasons:
        return
    folder = run_dir / breaker.BOGGART_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / breaker.LOG_NAME).open("a", encoding="utf-8") as log:
        log.write(f"{story_id} skipped: {'; '.join(reasons)}\n")


def _diff_facts(worktree, run_dir, origin, head, settings, risk):
    """Write the diff; return what the package says about it."""
    changed = _git(worktree, "diff", "--name-only", "-z", "--no-renames", origin, head).split("\0")
    risky_files = [path for path in changed if path and globs.matches_any(path, settings["risky_paths"])]
    diff = brief.write_file(run_dir / DIFF_NAME,
                            _git(worktree, "diff", "--no-color", "--no-ext-diff", "--no-textconv", origin, head))
    return {"head": head, "origin": origin, "diff": diff, "risky_files": risky_files,
            "code": has_code(path for path in changed if path), "breaker": bool(settings.get("breaker")),
            "ui": any(path and globs.matches_any(path, settings.get("ui_globs") or []) for path in changed),
            "preview": bool(settings.get("preview")), "test_data": _has_test_data(settings.get("preview")),
            "checklists": checklists(risk, bool(risky_files)),
            "shortstat": _git(worktree, "diff", "--shortstat", origin, head).strip() or "no changes"}


def _write(run_dir, text, facts):
    target = brief.write_file(run_dir / PACKAGE_NAME, text)
    return {"package": str(target), "diff": str(facts["diff"]), "head": facts["head"],
            "risky": bool(facts["risky_files"]) or SECURITY in facts["checklists"],
            **{flag: facts[flag] for flag in ("code", "breaker", "ui", "preview", "test_data")}}


def _has_test_data(preview):
    """True when config's `preview` mapping says `"test_data": true` (S-061/3)."""
    return bool(preview) and preview.get("test_data") is True  # config.load gives a read-only mapping, not a dict


def _read_acceptance(path):
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise brief.BriefError(f"cannot read the acceptance file {path}: {error}") from error
    if not text:
        raise brief.BriefError(f"the acceptance file {path} is empty; list what the fix must do")
    return text


def package_fix(accio, main, branch, acceptance, settings):
    """The package for a direct fix: a branch that is not a story, its acceptance list in place of the DoD."""
    text = _read_acceptance(acceptance)
    if re.fullmatch(r"story/S-\d+", branch):
        raise brief.BriefError(f"{branch} is a story branch; review it with `accio-brief <ID> --review`")
    if not _succeeds(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"):
        raise brief.BriefError(f"there is no branch {branch} in {main}")
    head = _git(main, "rev-parse", f"refs/heads/{branch}").strip()
    origin = _git(main, "merge-base", settings["base_branch"], head).strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "fix"
    run_dir = accio / "run" / name
    facts = _diff_facts(main, run_dir, origin, head, settings, None)
    findings = "\n".join(f"- `{run_dir / f'{who}-findings.md'}`" for who in REVIEWERS)
    base = settings["base_branch"]
    values = {
        "story_id": name, "title": "direct fix", "worktree": main, "branch": branch, "head": head,
        "scope": f"Review the whole fix: the diff from `{origin}` (where the branch leaves `{base}`) to `{head}`.",
        "diff": facts["diff"], "shortstat": facts["shortstat"], "template": REFERENCES / "findings-template.md",
        "source_line": "- This is a direct fix, not a story: there is no story file or implementer's report.",
        "findings_line": f"Each reviewer writes to their own file:\n{findings}\nIn the format of "
                         f"`{REFERENCES / 'findings-template.md'}`.",
        "criteria_heading": "Acceptance list", "dod": text, "files_heading": "Files changed",
        "files": "- see the diff", "risky_files": brief.bullets(f"`{path}`" for path in facts["risky_files"]),
        "checklists": ", ".join(f"`{CHECKLISTS / n}`" for n in facts["checklists"]) or "none",
        "rules_line": rules_line(main, base, run_dir)}
    return _write(run_dir, brief.fill("review-package.md", values), facts)


def _render(parsed, accio, worktree, facts):
    scope = (f"Fix round: judge only the fix diff, from `{facts['origin']}` (the commit you reviewed last) to "
             f"`{facts['head']}`. Your findings file holds your earlier findings: mark each resolved or open, "
             "keeping its id." if facts["is_fix"] else
             f"Review the whole story: the diff from `{facts['origin']}` (where the story starts) to `{facts['head']}`.")
    listed = ", ".join(f"`{CHECKLISTS / name}`" for name in facts["checklists"]) or "none"
    return brief.fill("review-package.md", {
        **brief.common(parsed, worktree, accio), "scope": scope, "head": facts["head"], "diff": facts["diff"],
        "shortstat": facts["shortstat"], "findings": facts["findings"],
        "criteria_heading": "Definition of Done", "files_heading": "Files the story may change (plus their tests)",
        # The story only, never house-elf's report: a reviewer judges the code, not the builder's account (S-079).
        "source_line": f"- The story: `{accio / 'stories' / (parsed.meta['id'] + '.md')}`",
        "findings_line": f"Write them to `{facts['findings']}` (your name in place of `<reviewer>`), in the format "
                         f"of `{REFERENCES / 'findings-template.md'}`.",
        "template": REFERENCES / "findings-template.md", "dod": brief.dod_lines(parsed),
        "files": brief.bullets(f"`{path}`" for path in parsed.meta.get("files", ())),
        "risky_files": brief.bullets(f"`{path}`" for path in facts["risky_files"]), "checklists": listed,
        "story_file": accio / "stories" / f"{parsed.meta['id']}.md", "rules_line": facts["rules_line"]})
