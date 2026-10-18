"""The review package (DESIGN § 3.4 step 4, § 7.1; S-020): what a story's reviewers read, as files.

- The diff goes to `run/<ID>/review.diff`: the whole story (from where its diff starts, as accio-check takes it) on
  the first review; in a fix round, only the fix, from the commit reviewed last (`--since`), which must be an
  earlier commit of the story.
- `risky` (the workflow adds auror) when the diff under review (the whole story, or a fix round's fix) touches a
  `risky_paths` glob, or the story's `risk` field holds a security word. Paths are read NUL-separated, so a name git
  would quote (a tab, a `"`) still meets the globs as it is. The method checklists follow `references/checklists/README.md`; auror always gets the security one.
"""
import re
import subprocess

from accio_lib import brief, checks, globs

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
    """Write the diff and the package; return {package, diff, head, risky}."""
    story_id = parsed.meta["id"]
    run_dir = accio / "run" / story_id
    head = _git(worktree, "rev-parse", "HEAD").strip()
    try:
        start = checks.diff_start(run_dir, worktree, settings["base_branch"])
    except checks.CheckError as error:
        raise brief.BriefError(f"can't tell where {story_id}'s diff starts: {error}") from error
    origin = _fix_start(worktree, since, start) if since else start
    changed = _git(worktree, "diff", "--name-only", "-z", "--no-renames", origin, head).split("\0")
    risky_files = [path for path in changed if path and globs.matches_any(path, settings["risky_paths"])]
    picked = checklists(parsed.meta.get("risk"), bool(risky_files))
    diff = brief.write_file(run_dir / DIFF_NAME,
                            _git(worktree, "diff", "--no-color", "--no-ext-diff", "--no-textconv", origin, head))
    text = _render(parsed, accio, worktree, {
        "head": head, "origin": origin, "diff": diff, "is_fix": bool(since),
        "shortstat": _git(worktree, "diff", "--shortstat", origin, head).strip() or "no changes",
        "risky_files": risky_files, "checklists": picked, "findings": run_dir / "<reviewer>-findings.md"})
    target = brief.write_file(run_dir / PACKAGE_NAME, text)
    return {"package": str(target), "diff": str(diff), "head": head, "risky": bool(risky_files) or SECURITY in picked}


def _render(parsed, accio, worktree, facts):
    scope = (f"Fix round: judge only the fix diff, from `{facts['origin']}` (the commit you reviewed last) to "
             f"`{facts['head']}`. Your findings file holds your earlier findings: mark each resolved or open, "
             "keeping its id." if facts["is_fix"] else
             f"Review the whole story: the diff from `{facts['origin']}` (where the story starts) to `{facts['head']}`.")
    listed = ", ".join(f"`{CHECKLISTS / name}`" for name in facts["checklists"]) or "none"
    return brief.fill("review-package.md", {
        **brief.common(parsed, worktree, accio), "scope": scope, "head": facts["head"], "diff": facts["diff"],
        "shortstat": facts["shortstat"], "findings": facts["findings"],
        "template": REFERENCES / "findings-template.md", "dod": brief.dod_lines(parsed),
        "files": brief.bullets(f"`{path}`" for path in parsed.meta.get("files", ())),
        "risky_files": brief.bullets(f"`{path}`" for path in facts["risky_files"]), "checklists": listed,
        "story_file": accio / "stories" / f"{parsed.meta['id']}.md"})
