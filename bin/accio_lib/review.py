"""The review package (DESIGN § 3.4 step 4, § 7.1; S-020): what a story's reviewers read, as files.

- The diff goes to `run/<ID>/review.diff`: the whole story (from where its diff starts, as accio-check takes it) on
  the first review; in a fix round, only the fix, from the commit reviewed last (`--since`), which must be an
  earlier commit of the story.
- `risky` (the workflow adds auror) when the story's diff touches a `risky_paths` glob, or its `risk` field holds a
  security word. The method checklists follow `references/checklists/README.md`; auror always gets the security one.
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


def _fix_start(worktree, since):
    """`since`, checked: a commit that is an earlier commit of the story's HEAD."""
    found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}"], cwd=worktree,
                           capture_output=True, text=True, check=False)
    commit = found.stdout.strip()
    if found.returncode != 0 or subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=worktree,
                                               capture_output=True, check=False).returncode != 0:
        raise brief.BriefError(f"--since {since} is not an earlier commit of this story's branch")
    return commit


def package(accio, parsed, worktree, settings, since=None):
    """Write the diff and the package; return {package, diff, head, risky}."""
    story_id = parsed.meta["id"]
    run_dir = accio / "run" / story_id
    head = _git(worktree, "rev-parse", "HEAD").strip()
    start = checks.diff_start(run_dir, worktree, settings["base_branch"])
    origin = _fix_start(worktree, since) if since else start
    risky_files = [path for path in _git(worktree, "diff", "--name-only", "--no-renames", start, head).splitlines()
                   if globs.matches_any(path, settings["risky_paths"])]
    picked = checklists(parsed.meta.get("risk"), bool(risky_files))
    diff = brief.write_file(run_dir / DIFF_NAME,
                            _git(worktree, "diff", "--no-color", "--no-ext-diff", "--no-textconv", origin, head))
    text = _render(parsed, accio, worktree, {
        "head": head, "origin": origin, "diff": diff, "is_fix": bool(since),
        "shortstat": _git(worktree, "diff", "--shortstat", origin, head).strip() or "no changes",
        "risky_files": risky_files, "checklists": picked, "findings": run_dir / "findings-<reviewer>.md"})
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
