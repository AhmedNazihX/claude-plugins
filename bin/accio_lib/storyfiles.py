"""Writing accio's committed files safely (prophecy and owl): frontmatter values and sections changed in place,
every file of a change written or none, and a commit of exactly those files.

- A value is replaced on its own line, keeping a trailing comment and the line ending; a missing key is added before
  the closing `---`. A section's body is replaced or appended to; a missing section is added at the end.
- `write_all` stages each file beside its target, then swaps them all in; on a failure it puts back what it swapped
  and says which files it couldn't. Modes are kept (DEFAULT_MODE for a new file).
- `commit` adds the files and commits only them (`git commit --only`): anything else the user staged stays staged,
  each listed file goes in whole, files that already match HEAD need no commit, and a refused commit is unstaged
  again. It returns (commit id, None) or (None, git's reason).
"""
import os
import re
import subprocess
import tempfile

from accio_lib import story

VALUE_LINE = re.compile(r"^(?P<key>[^:#]+:[ \t]*)(?P<value>.*?)(?P<comment>[ \t]+#[ \t].*?)?(?P<eol>\r?\n)?$", re.DOTALL)
DEFAULT_MODE = 0o644


class WriteError(Exception):
    """A write or commit problem, written for the user."""


def _lines(path):
    with open(path, encoding="utf-8", newline="") as stream:
        return stream.read().splitlines(keepends=True)


def _eol(lines):
    return "\r\n" if lines and lines[0].endswith("\r\n") else "\n"


def with_fields(path, changes):
    """The story file's text with frontmatter values replaced (or added); comments and line endings are kept."""
    lines = _lines(path)
    where = story.key_lines(path)
    for key, value in changes.items():
        if key in where:
            match = VALUE_LINE.match(lines[where[key] - 1])
            lines[where[key] - 1] = f"{match['key']}{value}{match['comment'] or ''}{match['eol'] or ''}"
        else:
            closing = next(index for index, line in enumerate(lines) if index and line.strip() == story.MARKER)
            lines.insert(closing, f"{key}: {value}{_eol(lines)}")
            where = _key_lines(lines)
    return "".join(lines)


def _key_lines(lines):
    """Line numbers (1-based) of the frontmatter keys in `lines`."""
    found = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == story.MARKER:
            break
        key = line.split(":", 1)[0].strip()
        if ":" in line and not line.lstrip().startswith("#") and key in story.KEYS:
            found.setdefault(key, index + 1)
    return found


def with_section(text, heading, body, append=False):
    """`text` with the body of `## <heading>` replaced (or appended to); a missing section is added at the end."""
    lines = text.splitlines(keepends=True)
    eol = _eol(lines)
    title = f"## {heading}"
    start = next((index for index, line in enumerate(lines) if line.strip() == title), None)
    if start is None:
        ending = "" if not lines or lines[-1].endswith(("\n", "\r")) else eol
        return f"{text}{ending}{title}{eol}{body.rstrip()}{eol}"
    end = next((index for index in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s", lines[index])), len(lines))
    kept = lines[start + 1:end] if append else []
    while kept and not kept[-1].strip():
        kept = kept[:-1]
    block = "".join(kept) + "".join(f"{line}{eol}" for line in body.rstrip().splitlines())
    return "".join(lines[:start + 1]) + block + "".join(lines[end:])


def _read_bytes(target):
    try:
        with open(target, "rb") as stream:
            return stream.read()
    except FileNotFoundError:
        return None


def _stage(target, text):
    """A temp file beside `target` holding `text`, with the target's mode (or DEFAULT_MODE for a new file)."""
    handle, temporary = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".accio-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.chmod(temporary, os.stat(target).st_mode & 0o777 if os.path.exists(target) else DEFAULT_MODE)
    except OSError:
        os.unlink(temporary)
        raise
    return temporary


def _restore(swapped, originals):
    """Put back what was swapped in; returns the files that couldn't be put back."""
    failed = []
    for target in swapped:
        try:
            if originals[target] is None:
                os.unlink(target)
            else:
                with open(target, "wb") as stream:
                    stream.write(originals[target])
        except OSError:
            failed.append(target)
    return failed


def write_all(texts, what="the change"):
    """Write every file or none: each is staged beside its target first, then all are swapped in."""
    targets = {os.path.realpath(path): text for path, text in texts.items()}
    staged, swapped = {}, []
    try:
        originals = {target: _read_bytes(target) for target in targets}
        for target, text in targets.items():
            staged[target] = _stage(target, text)
        for target, temporary in staged.items():
            os.replace(temporary, target)
            swapped.append(target)
    except OSError as error:
        for target, temporary in staged.items():
            if target not in swapped and os.path.exists(temporary):
                os.unlink(temporary)
        failed = _restore(swapped, originals)
        if failed:
            raise WriteError(f"cannot write {what} ({error}), and these files couldn't be put back: "
                            f"{', '.join(failed)}; `git checkout -- <file>` restores them") from error
        raise WriteError(f"cannot write {what} ({error}); nothing was changed") from error


def _git(root, *args):
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except OSError as error:
        return subprocess.CompletedProcess(args, 1, "", f"git could not run: {error}")


def commit(root, files, message):
    """Commit exactly `files`; returns (commit id, None) or (None, git's reason). Unchanged files need no commit; a
    refused commit is unstaged again, so the user's next commit doesn't take the plan by surprise."""
    names = [os.path.relpath(os.path.realpath(path), os.path.realpath(root)) for path in files]
    added = _git(root, "add", "--", *names)
    if added.returncode != 0:
        return None, (added.stderr or added.stdout).strip() or "git add failed"
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD").stdout.strip()
    if head and _git(root, "diff", "--cached", "--quiet", "HEAD", "--", *names).returncode == 0:
        return head, None
    committed = _git(root, "commit", "-q", "-m", message, "--only", "--", *names)
    if committed.returncode != 0:
        _git(root, *(("reset", "-q", "--", *names) if head else ("rm", "-q", "--cached", "--", *names)))
        return None, (committed.stderr or committed.stdout).strip() or "git commit failed"
    return _git(root, "rev-parse", "HEAD").stdout.strip(), None


