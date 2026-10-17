"""Token cost per story and per iteration, read from workflow transcripts (DESIGN § 8, spike S-001 finding 4).

`agent()` reports no usage, so the numbers come afterwards from the run's transcript folder: each agent has an
`agent-<id>.jsonl` (assistant messages carry `usage`) and an `agent-<id>.meta.json` whose `description` is the
label brew gave it. A label that starts with a story id (`S-012 implement`) counts for that story.

Claude Code writes one transcript line per content block, and every line of one API response repeats its usage,
so usage is counted once per (message.id, requestId), keeping the last line (it holds the final output count).
A story's tokens are all four usage fields (input, cache creation, cache reads, output); the breakdown is kept so
budgets can be tuned. A story with any unreadable agent is "unknown" (None), never a partial number; an unreadable
agent that belongs to no requested story makes the iteration total partial.
"""
import json
import re

FIELDS = (("input", "input_tokens"), ("cache_creation", "cache_creation_input_tokens"),
          ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens"))
LABEL_STORY = re.compile(r"^(S-\d{3,})\b")
STOP_FACTOR = 2


class UnreadableTranscript(Exception):
    """A transcript or its meta file that can't be read; its story becomes unknown."""


def _label(meta_path):
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise UnreadableTranscript(f"{meta_path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("description", ""), str):
        raise UnreadableTranscript(f"{meta_path}: not an agent meta object")
    return data.get("description", "")


def _usage_of(event, transcript):
    """(dedupe key or None, {field: tokens}) for an assistant line with usage, else None."""
    if not isinstance(event, dict):
        raise UnreadableTranscript(f"{transcript}: a line is not a JSON object")
    message = event.get("message")
    if event.get("type") != "assistant":
        return None
    if not isinstance(message, dict):
        raise UnreadableTranscript(f"{transcript}: an assistant line has no message object")
    if not isinstance(message.get("usage"), dict):
        return None
    counts = {}
    for name, key in FIELDS:
        value = message["usage"].get(key) or 0
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise UnreadableTranscript(f"{transcript}: {key} is not a token count: {value!r}")
        counts[name] = value
    key = (message.get("id"), event.get("requestId")) if message.get("id") else None
    return key, counts


def _agent_usage(transcript):
    """Summed usage of one agent transcript, each API response once; raises UnreadableTranscript."""
    try:
        lines = transcript.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise UnreadableTranscript(f"{transcript}: {error}") from error
    by_response, unkeyed = {}, []
    for line in filter(str.strip, lines):
        try:
            found = _usage_of(json.loads(line), transcript)
        except ValueError as error:
            raise UnreadableTranscript(f"{transcript}: {error}") from error
        if found is None:
            continue
        key, counts = found
        if key is None:
            unkeyed.append(counts)
        else:
            by_response = {**by_response, key: counts}
    responses = [*by_response.values(), *unkeyed]
    return {name: sum(counts[name] for counts in responses) for name, _ in FIELDS}


def _run_dirs(run_dirs):
    """Run folders with duplicates removed (by resolved path), in order."""
    seen, unique = set(), []
    for run_dir in run_dirs:
        resolved = run_dir.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _agents(run_dirs):
    """(story id or None, usage or None when unreadable) for every agent transcript in the run folders."""
    for run_dir in _run_dirs(run_dirs):
        stems = {path.name.split(".", 1)[0] for path in (*run_dir.glob("agent-*.jsonl"), *run_dir.glob("agent-*.meta.json"))}
        for stem in sorted(stems):
            transcript = run_dir / f"{stem}.jsonl"
            try:
                label = _label(run_dir / f"{stem}.meta.json")
            except UnreadableTranscript:
                yield None, None
                continue
            match = LABEL_STORY.match(label)
            story_id = match.group(1) if match else None
            try:
                yield story_id, _agent_usage(transcript)
            except UnreadableTranscript:
                yield story_id, None


def story_tokens(run_dirs, story_ids):
    """{story: {tokens, breakdown}}, plus "_unattributed" tokens and "_unattributed_unknown"."""
    empty = {name: 0 for name, _ in FIELDS}
    sums = {story_id: dict(empty) for story_id in story_ids}
    seen, broken, unattributed, unattributed_unknown = set(), set(), 0, False
    for story_id, used in _agents(run_dirs):
        if used is None:
            if story_id in sums:
                broken.add(story_id)
            else:
                unattributed_unknown = True
        elif story_id in sums:
            seen.add(story_id)
            sums[story_id] = {name: sums[story_id][name] + used[name] for name in empty}
        else:
            unattributed += sum(used.values())
    result = {}
    for story_id in story_ids:
        known = story_id in seen and story_id not in broken
        result[story_id] = {"tokens": sum(sums[story_id].values()) if known else None,
                            "breakdown": sums[story_id] if known else None}
    return {**result, "_unattributed": unattributed, "_unattributed_unknown": unattributed_unknown}


def budget_for(parsed, budgets):
    """A story's token budget: its own `budget_tokens`, else config `budgets` for its track (a feature uses the
    story budget)."""
    return parsed.meta.get("budget_tokens", budgets["quick" if parsed.meta["track"] == "quick" else "story"])


def report(run_dirs, budgets):
    """Per-story tokens against budgets, the iteration total, and whether anything is unknown."""
    totals = story_tokens(run_dirs, tuple(budgets))
    stories = {}
    for story_id, budget in budgets.items():
        tokens = totals[story_id]["tokens"]
        stories[story_id] = {**totals[story_id], "budget": budget,
                             "over": tokens is not None and tokens > budget,
                             "stop": tokens is not None and tokens >= STOP_FACTOR * budget}
    known = [entry["tokens"] for entry in stories.values() if entry["tokens"] is not None]
    partial = len(known) < len(stories) or totals["_unattributed_unknown"]
    return {"stories": stories, "unattributed": totals["_unattributed"],
            "total": sum(known) + totals["_unattributed"], "partial": partial}


def describe(result):
    lines = []
    for story_id, entry in result["stories"].items():
        if entry["tokens"] is None:
            lines.append(f"{story_id}  unknown (a transcript is missing or unreadable)")
            continue
        flag = "  STOPPED: 2x budget" if entry["stop"] else ("  over budget" if entry["over"] else "")
        lines.append(f"{story_id}  {entry['tokens'] // 1000}k of {entry['budget'] // 1000}k{flag}")
    total = f"Total {result['total'] // 1000}k tokens" + (" (partial: something was unreadable)" if result["partial"] else "")
    return "\n".join([*lines, total])
