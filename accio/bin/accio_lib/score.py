"""A story's complexity score → its track and a split flag (DESIGN § 3.2, decision 002).

The weights and thresholds are first guesses, like the token budgets; tune them from real runs.
- every file the story touches adds FILE_WEIGHT
- a risky path or a `risk` field adds RISK_WEIGHT and forces the Story track or higher, whatever the size
- a dependency manifest in the files (a new dependency) adds DEPENDENCY_WEIGHT and rules out Quick
"""
import pathlib

from accio_lib import globs

FILE_WEIGHT = 1
RISK_WEIGHT = 2
DEPENDENCY_WEIGHT = 3
QUICK_MAX_SCORE = 2
STORY_MAX_SCORE = 10
DEPENDENCY_MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "Pipfile", "go.mod", "Cargo.toml",
                        "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts")


def assess(files, risk, risky_paths):
    """Return {score, track, split, parts}; parts says what the score was made of."""
    risky_files = [path for path in files if globs.matches_any(path, risky_paths)]
    dependency_files = [path for path in files if pathlib.PurePosixPath(path).name in DEPENDENCY_MANIFESTS]
    is_risky = bool(risky_files or risk)
    total = (len(files) * FILE_WEIGHT + (RISK_WEIGHT if is_risky else 0)
             + (DEPENDENCY_WEIGHT if dependency_files else 0))
    split = total > STORY_MAX_SCORE
    if split:
        track = "feature"
    elif total <= QUICK_MAX_SCORE and not is_risky and not dependency_files:
        track = "quick"
    else:
        track = "story"
    parts = {"files": len(files), "risk": risk or "", "risky_files": risky_files, "dependency_files": dependency_files}
    return {"score": total, "track": track, "split": split, "parts": parts}


def describe(result):
    """The plain-words lines accio-score prints."""
    parts = result["parts"]
    lines = [
        f"files {parts['files']} (x{FILE_WEIGHT})",
        f"risk {parts['risk'] or 'none'}; risky paths: {', '.join(parts['risky_files']) or 'none'}",
        f"new dependencies: {', '.join(parts['dependency_files']) or 'none'}",
        f"score {result['score']} → track {result['track']}"
        + (f" (above {STORY_MAX_SCORE}: split it)" if result["split"] else ""),
    ]
    return "\n".join(lines)
