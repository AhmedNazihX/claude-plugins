"""Recording the backlog `sort` wrote (DESIGN § 3.2, § 12.2): every story sound, then one commit.

`record` takes the story files quill wrote or changed. It refuses during a build (the build reads the stories), then
loads every story, so a bad file, a duplicate id, a missing dependency or a cycle stops it before anything is
written. It regenerates board.md and commits exactly the given stories and the board (`git commit --only`).
"""
from accio_lib import board, plan, runlock, storyfiles

COMMIT_MESSAGE = "chore(accio): sort {count} {noun}"


class BacklogError(Exception):
    """A backlog problem, written for the user."""


def record(accio, given):
    """Commit the given story files and board.md; returns {files, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise BacklogError("a build is running (run/brew.lock); sort after it ends")
    try:
        paths = plan.story_files(accio, given, "record")
    except plan.PlanError as error:
        raise BacklogError(str(error)) from error
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    try:
        storyfiles.write_all({accio / board.BOARD_NAME: board.render(stories, status)}, "board.md")
    except storyfiles.WriteError as error:
        raise BacklogError(str(error)) from error
    files = [*map(str, paths), str(accio / board.BOARD_NAME)]
    noun = "story" if len(paths) == 1 else "stories"
    commit, why = storyfiles.commit(accio.parent, files, COMMIT_MESSAGE.format(count=len(paths), noun=noun))
    return {"files": files, "commit": commit, "commit_error": why}
