"""The one "what's next" rule (DESIGN "One command: /accio", part 1).

`next_step` says what to do from where the board stands: the step, whether accio carries it on without asking
(`auto`), and today's plain sentence. session-start, map and /accio all read it through `accio-board next`.
"""
from . import runlock, story

# step -> auto: does accio carry on without asking the user?
AUTO = {"wait": False, "brew": True, "owl": False, "prophecy": False, "wand": False, "sort": True, "done": False}


def _stories(count, kind):
    return f"{count} {kind} {'story' if count == 1 else 'stories'}"


def _reply(step, sentence):
    return {"step": step, "auto": AUTO[step], "sentence": sentence}


def next_step(accio, status, workflows_off):
    """The one thing to do next: {"step", "auto", "sentence"}."""
    brew = "/accio:brew once workflows are on" if workflows_off else "/accio:brew"
    counts = {key: sum(1 for value in status.values() if value == key) for key in story.STATUSES}
    if runlock.is_held(accio / "run"):
        return _reply("wait", "a build is running; when it ends, review it with /accio:owl.")
    if counts["doing"]:
        return _reply("brew", f"a build stopped mid-way ({_stories(counts['doing'], 'unfinished')}); "
                              f"resume it with {brew}.")
    if counts["review"] or counts["blocked"]:
        work = [part for count, part in ((counts["review"], f"review {_stories(counts['review'], 'built')}"),
                                          (counts["blocked"], f"answer {_stories(counts['blocked'], 'blocked')}"))
                if count]
        return _reply("owl", f"{' and '.join(work)} with /accio:owl.")
    if counts["ready"]:
        return _reply("brew", f"build {_stories(counts['ready'], 'ready')} with {brew}.")
    if counts["backlog"]:
        return _reply("prophecy", "plan the next iteration with /accio:prophecy.")
    if not (accio / "design.md").is_file():
        return _reply("wand", "design what to build with /accio:wand.")
    if not status:
        return _reply("sort", "turn the design into stories with /accio:sort.")
    return _reply("done", "every story is done or dropped; design what comes next with /accio:wand.")
