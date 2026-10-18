"""run/owl.md, the one file `owl` reads (DESIGN § 3.5, § 7.2): at most 150 tokens per story.

For each story the build finished (status `review`): what changed, how to try it, its risks and its token cost,
taken from the sections of `run/<ID>/report.md` that the brief and the fix brief ask house-elf to write. A stacked
child names the parents to accept with it, and the ones that keep it from being accepted yet. For each blocked
story: its one question from `run/questions/<ID>.md`.
"""
import re

STORY_TOKEN_TARGET = 150
CHARS_PER_TOKEN = 4
STORY_CHARS = STORY_TOKEN_TARGET * CHARS_PER_TOKEN - 1  # the most characters estimate_tokens keeps within target
TITLE_CHARS = 60
PARENTS_SHOWN = 2
REPORT_SECTIONS = (("What changed", "Changed"), ("How to try it", "Try it"), ("Risks", "Risks"))
MISSING_SECTION = "(missing from the report)"
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*:?\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
FOOTER = ("\nAnswer in one batch: accept, reject or drop each ready story (with a reason for reject or drop), "
          "answer each question, and say whether to push.\n")


def estimate_tokens(text):
    return len(text) // CHARS_PER_TOKEN + 1


def _clip(text, limit):
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[:max(limit - 1, 0)].rstrip() + "…"


def _fence_after(fence, line):
    """The fence still open after `line` (its opening run of ``` or ~~~), or None. Only the same character, at
    least as many times and nothing after it, closes a fence."""
    marker = FENCE.match(line)
    if not marker:
        return fence
    run = marker.group(1)
    if fence is None:
        return run
    closes = run[0] == fence[0] and len(run) >= len(fence) and line.strip() == run
    return None if closes else fence


def _sections(markdown):
    """{heading in lower case: its text} for each heading outside a code fence (any level, an optional `:`).
    A section runs to the next heading at its own level or above, so its subsections stay inside it."""
    sections, open_headings, fence = {}, (), None
    for line in markdown.splitlines():
        was_in_fence, fence = fence, _fence_after(fence, line)
        heading = None if was_in_fence else HEADING.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            open_headings = tuple((lvl, key) for lvl, key in open_headings if lvl < level)
        text = heading.group(2) if heading else line  # a subheading's title is part of its parents' text
        sections = {**sections, **{key: (*sections[key], text) for _, key in open_headings}}
        if heading:
            open_headings = (*open_headings, (level, title.lower()))
            sections = {**sections, title.lower(): sections.get(title.lower(), ())}
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _read(path):
    """(text, None), or (None, "missing") / (None, "unreadable")."""
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError):
        return None, "unreadable"


def _cost(entry):
    if entry is None or entry.get("tokens") is None:
        return "cost unknown"
    fresh = entry.get("fresh", entry["tokens"])
    cached = entry["tokens"] - fresh
    extra = (" (over budget)" if entry.get("over") else "") + (f" (+{cached // 1000}k cache reads)" if cached else "")
    return f"{fresh // 1000}k tokens{extra}"


def _heading(parsed, state, cost_entry):
    return f"### {parsed.meta['id']} {_clip(parsed.meta['title'], TITLE_CHARS)} — {state}, {_cost(cost_entry)}"


def _names(items):
    more = len(items) - PARENTS_SHOWN
    return ", ".join(items[:PARENTS_SHOWN]) + (f" +{more} more" if more > 0 else "")


def _parent_lines(parsed, status):
    """Parents in review must be accepted too; any other unfinished parent means it can't be accepted yet."""
    unfinished = [dep for dep in parsed.meta.get("deps", ()) if status.get(dep) != "done"]
    in_review = [dep for dep in unfinished if status.get(dep) == "review"]
    waiting = [f"{dep} is {status.get(dep, 'missing')}" for dep in unfinished if status.get(dep) != "review"]
    accept = (f"- Stacked: to accept it, accept {_names(in_review)} too.",) if in_review else ()
    blocked = (f"- It can't be accepted yet: {_names(waiting)}.",) if waiting else ()
    return accept + blocked


def _section_lines(report_text, room):
    """One line per report section, each clipped so that together they fit in `room` characters."""
    found = _sections(report_text)
    per_line = room // len(REPORT_SECTIONS)
    lines = []
    for heading, label in REPORT_SECTIONS:
        prefix = f"- {label}: "
        text = found.get(heading.lower()) or MISSING_SECTION
        lines.append(prefix + _clip(text, per_line - len(prefix) - 1))  # 1 for the newline before it
    return tuple(lines)


def ready_block(parsed, status, report, cost_entry):
    """`report` is the (text, problem) pair from _read."""
    heading, (report_text, problem) = _heading(parsed, "READY", cost_entry), report
    parents = _parent_lines(parsed, status)
    if problem:
        body = ("- (no report written)" if problem == "missing" else "- (report unreadable)",)
    else:
        body = _section_lines(report_text, STORY_CHARS - len(heading) - sum(len(line) + 1 for line in parents))
    return "\n".join((heading, *body, *parents))


def blocked_block(parsed, question, cost_entry):
    """`question` is the (text, problem) pair from _read."""
    heading, (text, problem) = _heading(parsed, "BLOCKED", cost_entry), question
    prefix = "\n- Question: "
    if problem == "unreadable":
        asked = "(question file unreadable)"
    else:
        asked = (text or "").strip() or "(no question recorded)"
    return heading + prefix + _clip(asked, STORY_CHARS - len(heading) - len(prefix))


def render(stories, status, run_dir, costs):
    """The owl.md text for every story in review or blocked."""
    blocks = []
    for story_id in sorted(stories):
        parsed, entry = stories[story_id], costs.get(story_id)
        if status[story_id] == "review":
            blocks.append(ready_block(parsed, status, _read(run_dir / story_id / "report.md"), entry))
        elif status[story_id] == "blocked":
            blocks.append(blocked_block(parsed, _read(run_dir / "questions" / f"{story_id}.md"), entry))
    body = "\n\n".join(blocks) or "Nothing is ready or blocked."
    return f"# Review\n\n{body}\n{FOOTER}"


def report_sections():
    """The report sections both briefs ask house-elf to write, so this summary can find them (one source)."""
    return ", ".join(f"`## {heading}`" for heading, _ in REPORT_SECTIONS)
