#!/usr/bin/env python3
"""Read, check, plan and update a story backlog (docs/BACKLOG.md by default). Stdlib only.

Usage (from anywhere inside the repo):
  backlog.py check               validate: duplicate IDs, unknown deps, cycles, missing Type/Output/DoD
  backlog.py plan [--width N]    critical path and waves, computed from the deps
  backlog.py status              done / in progress / ready / blocked, and the next wave
  backlog.py show <ID>           print one story's full entry
  backlog.py deps <ID>           list unmet deps; exit 1 if any are unmet
  backlog.py info <ID>           JSON: id, title, slug, lane, type, size, solo, resources, deps, done
  backlog.py tick <ID> <note>    mark a story [x] and add an outcome note
  backlog.py note <ID> [--from <SRC>] <text>
                                 add a hand-over note to a story ("**From SRC (merged):** text" with --from)
  backlog.py set-deps <ID> <deps>
                                 replace a story's Deps: field (refused if it would create a cycle)
  backlog.py add --after <ID>    insert a new story entry read from stdin after <ID>'s entry
  backlog.py graph               Mermaid flowchart of the critical path
Options: --file PATH (default: <repo root>/docs/BACKLOG.md)

Story format (one line, then indented lines for Context/Input/Output/DoD):
  - [ ] **C1 · Import parser** · Deps: B1, F4 · Type: agent · Lane: Data · Size: M · Resource: db-schema
IDs: 1–3 capital letters, a number, an optional lower-case suffix (F1, API12, P2a).
Grouped entries: "B5a–e" is one entry with sub-stories B5a … B5e; "B5" also refers to the group.
Deps: comma-separated IDs; ranges "E2–E7"; "–" means none; any other text is a manual condition.
Size: S=1, M=2, L=3 (default M), used to weight the critical path.
Solo: the story runs alone (nothing else in its wave). Resource: at most one story per resource per wave.

`check` also prints warnings (they don't fail it):
  - a story whose text mentions a shared resource (a migration, a lockfile) but has no matching Resource: tag;
  - a story whose Input or DoD names another open story, or a path another open story's Output creates,
    that isn't among its (transitive) Deps: it may look ready before it can finish.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ID = r"[A-Z]{1,3}\d+[a-z]?"
STORY_RE = re.compile(rf"^- \[( |x)\] \*\*(?P<id>{ID}(?:–[a-z])?) · (?P<title>[^*]+)\*\*(?P<rest>.*)$")
DEP_RE = re.compile(r"\b([A-Z]{1,3})(\d+)([a-z]?)(?:\s*[–-]\s*(?:([A-Z]{1,3})?(\d+))?([a-z])?)?\b")
SIZES = {"S": 1, "M": 2, "L": 3}
# A word in a story's text → the Resource: tag it suggests.
RESOURCE_HINTS = {
    r"\bmigrations?\b": "db-schema",
    # not "--frozen-lockfile": installing from a lockfile doesn't change it
    r"(?<![-\w])(?:lockfile|uv\.lock|pnpm-lock\.yaml|package-lock\.json|poetry\.lock|Cargo\.lock)\b": "lockfile",
}
NOTE_RE = re.compile(r"^\s*\*\*")  # "**Outcome:**", "**From C4:**" … notes, not the story's own fields
FIELD_RE = re.compile(r"\b(Context|Input|Output|DoD|Notes from merged stories):")
PATH_RE = re.compile(r"`([\w./-]+/[\w.-]+|[\w-]+\.[a-z]{2,4})`")


@dataclass(eq=False)  # stories compare and hash by identity
class Story:
    id: str
    title: str
    done: bool
    header: str
    body: list[str] = field(default_factory=list)
    line_no: int = 0

    def field(self, name: str) -> str:
        m = re.search(rf"\b{name}:\s*([^·]+)", self.header)
        return m.group(1).strip() if m else ""

    @property
    def type(self) -> str:
        t = self.field("Type")
        return t.split()[0].rstrip(",") if t else ""

    @property
    def lane(self) -> str:
        return re.sub(r"\s*\(.*\)$", "", self.field("Lane"))

    @property
    def size(self) -> int:
        return SIZES.get(self.field("Size")[:1].upper(), 2)

    @property
    def solo(self) -> bool:
        return bool(re.search(r"·\s*Solo\b", self.header))

    @property
    def resources(self) -> list[str]:
        return [r.strip() for r in self.field("Resource").split(",") if r.strip()]

    @property
    def sub_ids(self) -> list[str]:
        m = re.fullmatch(r"([A-Z]{1,3}\d+)([a-z])–([a-z])", self.id)
        if not m:
            return []
        return [m.group(1) + chr(c) for c in range(ord(m.group(2)), ord(m.group(3)) + 1)]

    @property
    def keys(self) -> list[str]:
        return [self.id] if not self.sub_ids else [self.id, self.sub_ids[0][:-1], *self.sub_ids]

    @property
    def subs_done(self) -> set[str]:
        return {m.group(1) for line in self.body if (m := re.search(rf"\*\*Outcome \(({ID})\):\*\*", line))}

    def is_done(self, sid: str) -> bool:
        return self.done or (sid in self.sub_ids and sid in self.subs_done)

    @property
    def slug(self) -> str:
        words = re.sub(r"[^a-z0-9 ]+", " ", self.title.lower().replace("`", "")).split()
        stop = {"the", "a", "an", "and", "of", "for", "with", "into", "as", "in", "to", "one", "per", "on"}
        return "-".join([w for w in words if w not in stop][:4]) or self.id.lower()

    def has_line(self, label: str) -> bool:
        return any(re.search(rf"\b{label}:", line) for line in [self.header, *self.body])

    @property
    def own_lines(self) -> list[str]:
        """The story's header and field lines, without the notes later stories added."""
        return [self.header, *(line for line in self.body if line.strip() and not NOTE_RE.match(line))]

    def fields(self, *names: str) -> str:
        """The text of the named fields (a line may hold several: 'Output: … DoD: …')."""
        parts: list[str] = []
        for line in self.own_lines:
            marks = list(FIELD_RE.finditer(line))
            for i, m in enumerate(marks):
                if m.group(1) in names:
                    end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
                    parts.append(line[m.end():end])
        return " ".join(parts)

    @property
    def resource_hints(self) -> list[str]:
        """Resource tags the story's text (handover notes included, outcome notes not) suggests but its
        header doesn't have."""
        text = " ".join([self.header, *(line for line in self.body if "**Outcome" not in line)])
        found = {tag for pattern, tag in RESOURCE_HINTS.items() if re.search(pattern, text, re.IGNORECASE)}
        return sorted(found - set(self.resources))


def parse_deps(text: str) -> tuple[list[str], list[str]]:
    """Return (story IDs, manual conditions)."""
    ids: list[str] = []
    notes: list[str] = []
    for part in [p.strip() for p in text.split(",") if p.strip()]:
        if part[0] in "–-":
            remark = part.lstrip("–- ").strip("() ")
            if remark:
                notes.append(remark)
            continue
        found = False
        for m in DEP_RE.finditer(part.replace("*", "")):
            letters, start, suffix, end_letters, end, end_suffix = m.groups()
            found = True
            if end and end_letters in (None, letters):
                ids += [f"{letters}{n}" for n in range(int(start), int(end) + 1)]
            elif end and end_letters:  # "C1–D3" has no order across letters: read both ends, flag it
                ids += [f"{letters}{start}{suffix}", f"{end_letters}{end}{end_suffix or ''}"]
                notes.append(f"range across letters read as its two ends: {m.group(0)}")
            elif end_suffix and suffix:
                ids += [f"{letters}{start}{chr(c)}" for c in range(ord(suffix), ord(end_suffix) + 1)]
            else:
                ids.append(f"{letters}{start}{suffix}")
        # Text beside an ID ("B3 committed", "F4 (a few stories have run)") is kept as a manual condition.
        clean = part.replace("*", "").strip()
        if found and DEP_RE.sub("", clean).strip(" ()"):
            notes.append(clean)
        if not found:
            notes.append(part)
    return list(dict.fromkeys(ids)), notes


class Backlog:
    def __init__(self, path: Path):
        self.path = path
        with open(path, encoding="utf-8", newline="") as f:  # newline="": see the file's own line endings
            raw = f.read()
        self.newline = "\r\n" if "\r\n" in raw else "\n"  # writes keep the file's line endings
        self.lines = raw.splitlines()
        self.stories: list[Story] = []
        current: Story | None = None
        for i, line in enumerate(self.lines):
            m = STORY_RE.match(line)
            if m:
                current = Story(m["id"], m["title"].strip(), line[3] == "x", line, line_no=i)
                self.stories.append(current)
            elif current and (line.startswith("  ") or line == ""):
                current.body.append(line)
            else:
                current = None
        self.by_key = {k: s for s in self.stories for k in s.keys}

    def find(self, sid: str) -> Story:
        if sid not in self.by_key:
            sys.exit(f"No story {sid} in {self.path}")
        return self.by_key[sid]

    def deps(self, s: Story) -> list[Story]:
        ids, _ = parse_deps(s.field("Deps"))
        return list(dict.fromkeys(self.by_key[i] for i in ids if i in self.by_key and self.by_key[i] is not s))

    def unmet(self, s: Story) -> tuple[list[str], list[str]]:
        ids, notes = parse_deps(s.field("Deps"))
        missing = [i for i in ids if i in self.by_key and not self.by_key[i].is_done(i)]
        # An unknown ID inside a written condition ("GPT4 access") is part of the condition, not a story.
        unknown = [i for i in ids if i not in self.by_key and not any(re.search(rf"\b{i}\b", n) for n in notes)]
        return missing, notes + [f"unknown story {u}" for u in unknown]

    def ancestors(self, s: Story) -> set[str]:
        """IDs `s` depends on, directly or through other stories. A dep on a whole group (B5, B5a–e) covers all
        its sub-stories; a dep on one sub-story (B5b) covers only that one."""
        covered: set[str] = set()
        visited: set[int] = set()
        todo = [s]
        while todo:
            current = todo.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            for dep_id in parse_deps(current.field("Deps"))[0]:
                dep = self.by_key.get(dep_id)
                if not dep:
                    continue
                covered |= set(dep.keys) if dep_id not in dep.sub_ids else {dep_id}
                todo.append(dep)
        return covered

    def dod_input_gaps(self, s: Story) -> list[str]:
        """Open stories that s's Input or DoD needs (by ID, or by a path their Output creates) but that aren't
        among its Deps. The group of a sub-story counts as covering it only once that sub-story is done."""
        if s.done:
            return []
        text = s.fields("Input", "DoD")
        covered = self.ancestors(s) | set(s.keys)
        gaps: dict[str, str] = {}
        for m in re.finditer(rf"\b({ID})\b", text):
            other = self.by_key.get(m.group(1))
            if other and other is not s and m.group(1) not in covered and not other.is_done(m.group(1)):
                gaps[m.group(1)] = f"{s.id}'s Input/DoD names {m.group(1)}, which isn't in its Deps"
        paths = set(PATH_RE.findall(text))
        for other in self.stories:
            if other is s or other.done or covered & set(other.keys):
                continue
            made = paths & set(PATH_RE.findall(other.fields("Output")))
            if made:
                gaps[other.id] = f"{s.id}'s Input/DoD uses {', '.join(sorted(made))}, which {other.id}'s Output creates"
        return list(gaps.values())

    # ---- graph ----
    def order(self) -> list[Story]:
        """Topological order; exits with the cycle if there is one."""
        state: dict[str, int] = {}
        out: list[Story] = []

        def visit(s: Story, stack: list[str]) -> None:
            if state.get(s.id) == 2:
                return
            if state.get(s.id) == 1:
                cycle = stack[stack.index(s.id):] + [s.id]
                sys.exit(f"Dependency cycle: {' → '.join(cycle)}")
            state[s.id] = 1
            for d in self.deps(s):
                visit(d, stack + [s.id])
            state[s.id] = 2
            out.append(s)

        for s in self.stories:
            visit(s, [])
        return out

    def critical_path(self, include_done: bool = True) -> list[Story]:
        best: dict[str, tuple[int, Story | None]] = {}
        for s in self.order():
            w = 0 if (s.done and not include_done) else s.size
            prev = max(((best[d.id][0], d) for d in self.deps(s)), key=lambda t: t[0], default=(0, None))
            best[s.id] = (prev[0] + w, prev[1])
        if not best:
            return []
        end = max(self.stories, key=lambda s: best[s.id][0])
        chain: list[Story] = []
        node: Story | None = end
        while node:
            chain.append(node)
            node = best[node.id][1]
        return list(reversed(chain))

    def descendants(self) -> dict[str, int]:
        children: dict[str, set[str]] = {s.id: set() for s in self.stories}
        for s in self.stories:
            for d in self.deps(s):
                children[d.id].add(s.id)
        memo: dict[str, set[str]] = {}

        def reach(i: str) -> set[str]:
            if i not in memo:
                memo[i] = set(children[i]).union(*[reach(c) for c in children[i]]) if children[i] else set()
            return memo[i]

        return {i: len(reach(i)) for i in children}

    def waves(self, width: int = 0) -> list[list[Story]]:
        """Greedy schedule of the open stories: deps first, critical path first, Solo alone,
        one story per Resource per wave, at most `width` stories per wave (0 = no limit)."""
        self.order()  # fails loudly on cycles
        crit = {s.id for s in self.critical_path(include_done=False)}
        fan = self.descendants()
        done = {s.id for s in self.stories if s.done}
        todo = [s for s in self.stories if not s.done]
        result: list[list[Story]] = []

        def deps_met(s: Story) -> bool:
            """Like `unmet`: a dep on one sub-story (B5a) waits for that sub-story, not the whole group."""
            for dep_id in parse_deps(s.field("Deps"))[0]:
                dep = self.by_key.get(dep_id)
                if dep is None or dep is s:
                    continue
                if not (dep.is_done(dep_id) or dep.id in done):
                    return False
            return True

        while todo:
            ready = [s for s in todo if deps_met(s)]
            ready.sort(key=lambda s: (s.id not in crit, -fan[s.id], s.line_no))
            wave: list[Story] = []
            used: set[str] = set()
            for s in ready:
                if width and len(wave) >= width:
                    break
                if s.solo:
                    if not wave:
                        wave = [s]
                    break
                if used & set(s.resources):
                    continue
                wave.append(s)
                used |= set(s.resources)
            result.append(wave)
            done |= {s.id for s in wave}
            todo = [s for s in todo if s not in wave]
        return result


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


def branches() -> set[str]:
    out = subprocess.run(["git", "branch", "--format=%(refname:short)"], capture_output=True, text=True)
    return set(out.stdout.split())


# ---- commands ----
def story_problems(b: Backlog, s: Story) -> list[str]:
    """What `check` fails a story for: missing fields, an unknown Type, unknown deps."""
    problems: list[str] = []
    if not s.field("Deps"):
        problems.append(f"{s.id}: no 'Deps:' field (use 'Deps: –' for none)")
    if s.type not in {"agent", "human", "mixed"}:
        problems.append(f"{s.id}: Type is '{s.type or 'missing'}' (expected agent, human or mixed)")
    if not s.has_line("Output"):
        problems.append(f"{s.id}: no 'Output:'")
    if not s.has_line("DoD"):
        problems.append(f"{s.id}: no 'DoD:'")
    _, notes = b.unmet(s)
    return problems + [f"{s.id}: {n}" for n in notes if n.startswith("unknown story")]


def cmd_check(b: Backlog) -> int:
    problems: list[str] = []
    seen: dict[str, Story] = {}
    for s in b.stories:
        for k in s.keys:
            if k in seen and seen[k] is not s:
                problems.append(f"duplicate ID {k} (lines {seen[k].line_no + 1} and {s.line_no + 1})")
            seen[k] = s
        problems += story_problems(b, s)
    b.order()  # exits on a cycle
    warnings: list[str] = []
    for s in b.stories:
        if not s.done and s.resource_hints:
            warnings.append(f"{s.id}: mentions {', '.join(s.resource_hints)} work but has no matching 'Resource:' tag")
        warnings += b.dod_input_gaps(s)
    for p in problems:
        print(f"  - {p}")
    for w in warnings:
        print(f"  ! {w}")
    summary = "OK" if not problems else f"{len(problems)} problem(s)"
    print(f"{len(b.stories)} stories checked: {summary}{f', {len(warnings)} warning(s)' if warnings else ''}")
    return 1 if problems else 0


def cmd_plan(b: Backlog, width: int) -> None:
    path = b.critical_path()
    total = sum(s.size for s in path)
    print(f"## Critical path ({len(path)} stories, weight {total})")
    print("  " + " → ".join(f"{s.id}{'✓' if s.done else ''}" for s in path))
    print("\n## Waves (open stories)")
    crit = {s.id for s in path}

    def label(s: Story) -> str:
        tags = [t for t, on in (("solo", s.solo), ("check", bool(b.unmet(s)[1]))) if on]
        return f"{s.id}{'*' if s.id in crit else ''}{f' ({', '.join(tags)})' if tags else ''}"

    for i, wave in enumerate(b.waves(width), 1):
        print(f"  {i:>2}. {', '.join(label(s) for s in wave)}")
    print("\n  * on the critical path · (solo) runs alone · (check) has a manual condition in its Deps")


def cmd_status(b: Backlog) -> None:
    live = branches()
    groups: dict[str, list[str]] = {"In progress": [], "Ready": [], "Blocked": []}
    done = [s for s in b.stories if s.done]
    for s in b.stories:
        if s.done:
            continue
        label = f"{s.id} · {s.title}"
        if s.sub_ids:
            left = [i for i in s.sub_ids if i not in s.subs_done]
            label += f"  (sub-stories left: {', '.join(left) or 'none, tick the group'})"
        missing, notes = b.unmet(s)
        if any(br.startswith(f"story/{k}-") for k in s.keys for br in live):
            groups["In progress"].append(f"{label}  [{s.type}]")
        elif missing:
            groups["Blocked"].append(f"{label}  ← waiting on {', '.join(missing)}")
        else:
            extra = f"  (check: {'; '.join(notes)})" if notes else ""
            tags = [s.type, *([f"lane {s.lane}"] if s.lane else []), *s.resources,
                    *(f"{h}?" for h in s.resource_hints)]
            gaps = b.dod_input_gaps(s)
            if gaps:
                extra += f"  (ready to build, not to finish: {'; '.join(gaps)})"
            groups["Ready"].append(f"{label}  [{', '.join(tags)}]{extra}")
    print(f"Backlog: {len(done)}/{len(b.stories)} stories done\n")
    for name, items in groups.items():
        print(f"## {name} ({len(items)})")
        for item in items:
            print(f"  - {item}")
        print()
    print(f"## Done ({len(done)})\n  {', '.join(s.id for s in done) or 'none'}\n")
    path = b.critical_path()
    nxt = next((s for s in path if not s.done), None)
    print(f"## Critical path\n  {' → '.join(s.id + ('✓' if s.done else '') for s in path)}")
    print(f"  next on the path: {nxt.id if nxt else 'complete'}")
    if nxt and (waiting := b.unmet(nxt)[0]):
        print(f"  {nxt.id} is waiting on {', '.join(waiting)}: start those first")
    waves = b.waves()
    if waves:
        print(f"\n## Next wave\n  {', '.join(s.id for s in waves[0])}")


def cmd_tick(b: Backlog, sid: str, note: str) -> None:
    s = b.find(sid)
    sub = sid in s.sub_ids
    if s.done:
        sys.exit(f"{s.id} is already ticked")
    if sub and sid in s.subs_done:
        sys.exit(f"{sid} already has an outcome note")
    if not sub and s.sub_ids and (left := [i for i in s.sub_ids if i not in s.subs_done]):
        sys.exit(f"Can't tick {s.id}: sub-stories without an outcome note: {', '.join(left)}")
    lines = b.lines
    if not sub:
        lines[s.line_no] = lines[s.line_no].replace("- [ ]", "- [x]", 1)
    last = s.line_no + len(s.body)
    while last > s.line_no and lines[last].strip() == "":
        last -= 1
    lines.insert(last + 1, f"  **Outcome{f' ({sid})' if sub else ''}:** {note}")
    b.path.write_text(b.newline.join(lines) + b.newline, encoding="utf-8", newline="")
    print(f"Added the outcome note for {sid}." if sub else f"Ticked {s.id} and added the outcome note.")


def entry_end(b: Backlog, s: Story) -> int:
    """Index of the last non-blank line of a story's entry."""
    last = s.line_no + len(s.body)
    while last > s.line_no and b.lines[last].strip() == "":
        last -= 1
    return last


def write_checked(b: Backlog, lines: list[str], what: str, touched: tuple[str, ...] = ()) -> None:
    """Write the edited backlog only if it has no duplicate IDs, no cycle, and the touched stories still pass
    `check`; otherwise leave the file as it was. The write is atomic and keeps the file's line endings."""
    fd, tmp_name = tempfile.mkstemp(suffix=".md", dir=b.path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(b.newline.join(lines) + b.newline)
        trial = Backlog(tmp)
        seen: dict[str, Story] = {}
        for s in trial.stories:
            for k in s.keys:
                if k in seen and seen[k] is not s:
                    sys.exit(f"Not written: duplicate ID {k}")
                seen[k] = s
        try:
            trial.order()
        except SystemExit as e:
            sys.exit(f"Not written: {e}")
        problems = [p for sid in touched if sid in trial.by_key for p in story_problems(trial, trial.by_key[sid])]
        if problems:
            sys.exit("Not written: " + "; ".join(problems))
        os.replace(tmp, b.path)
    finally:
        tmp.unlink(missing_ok=True)
    print(what)


def cmd_note(b: Backlog, sid: str, text: str, source: str | None) -> None:
    """Add a hand-over note at the end of a story's entry. A sub-story's note goes on its group, marked (B5b)."""
    s = b.find(sid)
    text = text.strip()
    if not text or "\n" in text or "\r" in text:
        sys.exit("A note is one non-empty line: run `note` once per line")
    if re.match(r"(\*\*Outcome\b|- \[[ x]\])", text):
        sys.exit("A note can't start with **Outcome or a story line: `tick` writes outcomes, `add` adds stories")
    if sid in s.sub_ids:
        text = f"({sid}) {text}"
    note = f"**From {source} (merged):** {text}" if source else text
    lines = list(b.lines)
    lines.insert(entry_end(b, s) + 1, f"  {note}")
    write_checked(b, lines, f"Added a note to {s.id}.", (s.id,))


def cmd_set_deps(b: Backlog, sid: str, deps: str) -> None:
    """Replace a story's Deps: field (the rest of the header stays as it is)."""
    s = b.find(sid)
    if sid in s.sub_ids:
        sys.exit(f"{sid} shares its Deps with its group {s.id}: set them on {s.id}, or give {sid} its own entry")
    deps = deps.strip()
    if not deps or "·" in deps or "\n" in deps:
        sys.exit("Deps must be one line without '·' (use '–' for none)")
    if not re.search(r"\bDeps:\s*[^·]+", s.header):
        sys.exit(f"{s.id} has no 'Deps:' field to replace")
    lines = list(b.lines)
    lines[s.line_no] = re.sub(r"\bDeps:\s*[^·]+?(\s*·|\s*$)", lambda m: f"Deps: {deps}{m.group(1)}", s.header, count=1)
    write_checked(b, lines, f"{s.id}: Deps: {deps}", (s.id,))


def cmd_add(b: Backlog, after: str, entry: str) -> None:
    """Insert a new story entry (its header line and indented lines, from stdin) after another story's entry."""
    new = [line.rstrip() for line in entry.strip().splitlines()]
    while new and not new[-1].strip():
        new.pop()
    if not new or not STORY_RE.match(new[0]):
        sys.exit("The entry must start with a story line: - [ ] **<ID> · <Title>** · Deps: … · Type: …")
    if any(line and not line.startswith("  ") for line in new[1:]):
        sys.exit("Every line after the story line must be indented by two spaces")
    anchor = b.find(after)
    lines = list(b.lines)
    at = entry_end(b, anchor) + 1
    lines[at:at] = ["", *new]
    new_id = STORY_RE.match(new[0])["id"]
    write_checked(b, lines, f"Added {new_id} after {anchor.id}.", (new_id,))


def cmd_graph(b: Backlog) -> None:
    path = b.critical_path()
    print("```mermaid\nflowchart LR")
    for a, c in zip(path, path[1:]):
        print(f"  {a.id} --> {c.id}")
    print("```")


def main(argv: list[str]) -> None:
    path = None
    for flag in ("--file", "--width"):
        if flag in argv and argv.index(flag) + 1 >= len(argv):
            sys.exit(f"{flag} needs a value\n\n{__doc__}")
    if "--file" in argv:
        i = argv.index("--file")
        path = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    width = 0
    if "--width" in argv:
        i = argv.index("--width")
        width = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        sys.exit(__doc__)
    if argv[0] in {"show", "deps", "info", "tick", "note", "set-deps"} and len(argv) < 2:
        sys.exit(f"'{argv[0]}' needs a story ID\n\n{__doc__}")
    if argv[0] in {"note", "set-deps"} and len(argv) < 3:
        sys.exit(f"'{argv[0]}' needs a story ID and a value\n\n{__doc__}")
    b = Backlog(path or repo_root() / "docs" / "BACKLOG.md")
    cmd, *args = argv
    if cmd == "check":
        sys.exit(cmd_check(b))
    elif cmd == "plan":
        cmd_plan(b, width)
    elif cmd == "status":
        cmd_status(b)
    elif cmd == "show":
        s = b.find(args[0])
        print("\n".join([s.header, *s.body]).rstrip())
    elif cmd == "deps":
        s = b.find(args[0])
        missing, notes = b.unmet(s)
        for m in missing:
            print(f"unmet: {m} · {b.by_key[m].title}")
        for n in notes:
            print(f"check by hand: {n}")
        sys.exit(1 if missing else 0)
    elif cmd == "info":
        s = b.find(args[0])
        ids, notes = parse_deps(s.field("Deps"))
        print(json.dumps({
            "id": s.id, "branch_id": args[0], "title": s.title, "slug": s.slug, "lane": s.lane,
            "type": s.type, "size": s.size, "solo": s.solo, "resources": s.resources,
            # sub_stories is only set for the group itself: a sub-story (B5b) is startable on its own.
            "deps": ids, "dep_notes": notes, "done": s.is_done(args[0]),
            "sub_stories": [] if args[0] in s.sub_ids else s.sub_ids,
            "resource_hints": s.resource_hints, "dod_input_gaps": b.dod_input_gaps(s),
        }, ensure_ascii=False))
    elif cmd == "tick":
        cmd_tick(b, args[0], " ".join(args[1:]) or "done")
    elif cmd == "note":
        source = None
        if "--from" in args:
            i = args.index("--from")
            if i + 1 >= len(args):
                sys.exit("--from needs a story ID")
            source = args[i + 1]
            args = args[:i] + args[i + 2:]
        cmd_note(b, args[0], " ".join(args[1:]), source)
    elif cmd == "set-deps":
        cmd_set_deps(b, args[0], " ".join(args[1:]))
    elif cmd == "add":
        if "--after" not in args or args.index("--after") + 1 >= len(args):
            sys.exit("add needs --after <ID>; the entry is read from stdin")
        cmd_add(b, args[args.index("--after") + 1], sys.stdin.read())
    elif cmd == "graph":
        cmd_graph(b)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
