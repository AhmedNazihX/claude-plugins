"""Setting accio up in a repo and recording its design (DESIGN § 3.1, § 12.1, § 12.2).

`init` creates `.accio/` in the main checkout (an empty `config.json`, which means every default, and a `stories/`
folder) and makes git ignore `.accio/run/`, the build's runtime state. It never changes what is already there, so a
second run is harmless. `record_design` commits `.accio/design.md` with the setup files, and nothing else the user
staged: it needs the design's `## Outcome` (decision 011) and refuses during a build.
"""
import re

from accio_lib import board, paths, runlock, storyfiles

RUN_IGNORE = ".accio/run/"
DESIGN_NAME = "design.md"
OUTCOME = re.compile(r"^## Outcome\s*$", re.MULTILINE)
COMMIT_MESSAGE = "docs(accio): design"


class DesignError(Exception):
    """A setup or design problem, written for the user."""


def init():
    """Set accio up in this repo; returns {accio, created}."""
    root = paths.main_root()
    if root is None:
        raise DesignError("this folder isn't in a git repo; accio needs one (run `git init` first)")
    accio = root / paths.ACCIO_DIR_NAME
    created = not accio.exists()
    texts = {}
    if not (accio / "config.json").exists():
        texts[accio / "config.json"] = "{}\n"
    ignore = root / ".gitignore"
    current = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if RUN_IGNORE not in current.splitlines():
        texts[ignore] = current + ("" if not current or current.endswith("\n") else "\n") + RUN_IGNORE + "\n"
    try:
        (accio / "stories").mkdir(parents=True, exist_ok=True)
        if texts:
            storyfiles.write_all(texts, "accio's setup")
    except (OSError, storyfiles.WriteError) as error:
        raise DesignError(f"cannot set accio up in {root}: {error}") from error
    return {"accio": str(accio), "created": created}


def record_design(accio):
    """Commit the design and the setup files; returns {files, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise DesignError("a build is running (run/brew.lock); record the design after it ends")
    design = accio / DESIGN_NAME
    try:
        text = design.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DesignError(f"there is no {design} to record yet") from error
    except (OSError, UnicodeDecodeError) as error:
        raise DesignError(f"cannot read {design}: {error}") from error
    if not OUTCOME.search(text):
        raise DesignError(f"{design} needs a `## Outcome` section: what should be true after it ships, and how "
                          "we'd know (decision 011)")
    files = [str(path) for path in (design, accio / "config.json", accio.parent / ".gitignore") if path.exists()]
    commit, why = storyfiles.commit(accio.parent, files, COMMIT_MESSAGE)
    return {"files": files, "commit": commit, "commit_error": why}
