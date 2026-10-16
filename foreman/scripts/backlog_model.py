"""The backlog model for backlog.py: story lines parsed into `Story` objects, the `Backlog` with its dependency
graph, and the checks `check` runs on one story. Stdlib only. Imported by backlog.py from the same folder.
"""

from __future__ import annotations

import re
import subprocess
import sys
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
