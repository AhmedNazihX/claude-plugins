"""How curfew judges a Bash command (DESIGN § 4.4; decision 010; S-015 review round 1).

A command is split into simple commands at `&&`, `||`, `;`, `|` and newlines; any other operator (`&`, a
subshell) is denied. Command substitutions and backticks can't be checked, so they are denied. A `NAME=value`
before a command is allowed only when a listed command includes it (it could point git or the loader anywhere).
`eval`, `source` or `bash -c …` run only if listed as such: a listed `bash tests/run.sh` doesn't cover `bash -c`.

With a worktree (house-elf), the command starts with `cd <worktree> &&` and never moves again, or is all
`git -C <worktree> …`. Output redirects land inside the worktree; in the `git -C` form a relative one would land
in the agent's own folder (the main checkout), so only `/dev/null` and fd copies are allowed there, as for the
other agents.

Programs are judged by `Judge`: listed commands match as a word prefix (a check or an `agent_allow` entry allows
that command with any further arguments); read-only tools lose the flags that write or run code, in any
abbreviation getopt accepts (`--out` for `--output`); file tools take plain flags only and stay in the worktree;
git takes an explicit list of subcommands. Nothing may touch a `.git` path in the worktree: its `.git` file names
the git folder, and pointing it at a config the agent wrote would run any command.

This stops mistakes, not a determined agent: a listed check runs test files the agent wrote. The walls are the git
hooks, the main snapshot and the remote check (DESIGN § 6).
"""
import dataclasses
import os
import pathlib
import re
import shlex

from accio_lib import shellpaths, shellwords

SPLIT_OPERATORS = frozenset({"&&", "||", ";", "|", "\n", ""})
READ_ONLY_PROGRAMS = frozenset({"ls", "cat", "head", "tail", "wc", "grep", "rg", "sort", "uniq", "diff", "echo",
                                "printf", "pwd", "test", "[", "true", "false", "which", "file", "stat", "tree",
                                "basename", "dirname", "realpath", "find"})
WRITING_SHORT_FLAGS = {"sort": "o", "tree": "o", "file": "C"}  # a short flag letter that writes a file
WRITING_LONG_FLAGS = {"sort": ("--output", "--compress-program"), "rg": ("--pre", "--pre-glob"),
                      "file": ("--compile",)}
FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                          "-fls"})
FILE_PROGRAMS = frozenset({"mkdir", "touch", "cp", "mv", "rm", "rmdir"})
PLAIN_FILE_FLAGS = re.compile(r"^-[prRfvna]+$")
HOUSE_ELF_GIT = frozenset({"add", "commit", "status", "diff", "log", "show", "rev-parse", "ls-files", "mv", "rm",
                           "restore", "blame", "grep", "merge-base", "rebase", "branch"})
READ_ONLY_GIT = frozenset({"status", "diff", "log", "show", "rev-parse", "merge-base", "ls-files", "cat-file",
                           "describe", "branch", "rev-list", "blame", "grep"})
GIT_FLAGS = frozenset({"--no-pager", "-p", "-P", "--paginate"})
LISTING_BRANCH_ARGS = frozenset({"--show-current", "--list", "-a", "-r", "-v", "-vv"})
REBASE_STEPS = frozenset({"--continue", "--abort", "--skip"})
GLOB_CHARS = frozenset("*?[")


@dataclasses.dataclass(frozen=True)
class Judge:
    """What one agent may run. `prefixes` are listed commands (word tuples); `git` is its subcommand list;
    `files` lets file tools act inside `worktree`; `scripts` are accio's script names, found in `bin_dir`;
    `may_cd` lets the command move between folders (prefect runs checks in a worktree)."""
    agent: str
    prefixes: tuple = ()
    read_only: bool = False
    files: bool = False
    git: frozenset = frozenset()
    scripts: frozenset = frozenset()
    bin_dir: pathlib.Path = None
    worktree: pathlib.Path = None
    may_cd: bool = False


def command_prefixes(commands, where):
    """Each configured command as a word tuple; a command that can't be split names its entry."""
    prefixes = []
    for command in commands:
        try:
            words = tuple(shlex.split(command))
        except ValueError as error:
            raise ValueError(f"config.json {where} `{command}` can't be read ({error}); fix it there") from error
        if words:
            prefixes.append(words)
    return tuple(prefixes)


def check(command, judge, start_in=None):
    """Why this command is denied, or None. With `start_in`, it must start in that folder (house-elf)."""
    if "$(" in command or "`" in command:
        return "a command substitution ($(…)) or backticks can't be checked; run the inner command on its own."
    segments = list(shellwords.segments(command))
    operator = next((segment.operator for segment in segments if segment.operator not in SPLIT_OPERATORS), None)
    if operator:
        return f"the shell operator `{operator}` isn't allowed; use &&, ||, ; or |."
    redirect_base = None
    if start_in is not None:
        segments, redirect_base, reason = _start_in(segments, start_in)
        if reason:
            return reason
    for segment in segments:
        reason = _judge_segment(segment.words, judge) if segment.words else None
        if reason:
            return reason
    return _redirects(command, redirect_base)


def _judge_segment(words, judge):
    program_words = program_part(words)
    if len(program_words) < len(words) and not _is_listed(words, judge):
        name = words[0].partition("=")[0]
        return f"setting `{name}` before a command isn't allowed unless the whole command is in agent_allow."
    return _judge_program(program_words, judge) if program_words else None


def _judge_program(words, judge):
    program = words[0]
    if _is_listed(words, judge) or _is_script(program, judge) or (program == "cd" and judge.may_cd):
        return None
    if program == "git" and judge.git:
        return _git(words, judge)
    if program in READ_ONLY_PROGRAMS and judge.read_only:
        return _read_only(words)
    if program in FILE_PROGRAMS and judge.files:
        return _file_program(words, judge.worktree)
    return f"`{' '.join(words[:2])}` isn't on accio:{judge.agent}'s list. Ask for it at owl."


def _is_listed(words, judge):
    return any(tuple(words[:len(prefix)]) == prefix for prefix in judge.prefixes)


def _is_script(word, judge):
    name = os.path.basename(word)
    if name not in judge.scripts:
        return False
    return word == name or os.path.realpath(word) == os.path.realpath(judge.bin_dir / name)


def program_part(words):
    """The words from the program on, after `NAME=value` assignments."""
    index = 0
    while index < len(words) and shellpaths.ASSIGNMENT.match(words[index]):
        index += 1
    return list(words[index:])


def _abbreviates(word, names):
    """True when `word` is one of these long options or a getopt abbreviation of one (`--out=x` for `--output`)."""
    name = word.split("=", 1)[0]
    return name.startswith("--") and len(name) > 2 and any(full.startswith(name) for full in names)


def _has_short_flag(words, letter):
    return any(word.startswith("-") and not word.startswith("--") and letter in word[1:] for word in words)


def _operands(words):
    """The non-option words; `-` (standard input) counts, and every word after `--`."""
    if "--" in words:
        cut = words.index("--")
        return [word for word in words[:cut] if word == "-" or not word.startswith("-")] + words[cut + 1:]
    return [word for word in words if word == "-" or not word.startswith("-")]


def _read_only(words):
    program, args = words[0], words[1:]
    letter = WRITING_SHORT_FLAGS.get(program)
    writes = (bool(letter) and _has_short_flag(args, letter)) or any(
        _abbreviates(arg, WRITING_LONG_FLAGS.get(program, ())) for arg in args)
    if program == "find":
        writes = bool(FIND_ACTIONS & set(args))
    if program == "uniq":
        writes = len(_operands(args)) > 1
    return f"`{program}` with an option that writes a file or runs code isn't allowed here." if writes else None


def _file_program(words, worktree):
    program, after_options = words[0], False
    for word in words[1:]:
        if word == "--" and not after_options:
            after_options = True
        elif word.startswith("-") and not after_options:
            if not PLAIN_FILE_FLAGS.match(word):
                return f"`{program}` option `{word.split('=')[0]}` isn't allowed; use plain flags (-p -r -f -v -n -a)."
        elif not in_worktree(resolve(word, worktree), worktree):
            return f"`{program}` may only touch files inside {worktree} (and never its .git), not {word}."
    return None


def _git(words, judge):
    index = 1
    while index < len(words) and words[index].startswith("-"):
        option = words[index]
        if option == "-C" and index + 1 < len(words):
            if judge.worktree is not None and not same_dir(words[index + 1], judge.worktree):
                return f"`git -C` must name {judge.worktree}."
            index += 2
        elif option in GIT_FLAGS:
            index += 1
        else:
            return f"git's global option `{option.split('=')[0]}` isn't allowed."
    subcommand, args = (words[index], words[index + 1:]) if index < len(words) else ("", [])
    if subcommand not in judge.git:
        return f"`git {subcommand}` isn't on accio:{judge.agent}'s list."
    return _git_args(subcommand, args)


def _git_args(subcommand, args):
    if any(_abbreviates(arg, ("--output",)) for arg in args):
        return "git's `--output` writes a file; print to the terminal instead."
    if subcommand == "grep" and (_has_short_flag(args, "O")
                                 or any(_abbreviates(arg, ("--open-files-in-pager",)) for arg in args)):
        return "`git grep -O` runs a program; print the matches instead."
    if subcommand == "branch" and not set(args) <= LISTING_BRANCH_ARGS:
        return "`git branch` may only list branches here (--show-current, --list, -a, -r, -v)."
    if subcommand == "rebase" and not (len(args) == 1 and args[0] in REBASE_STEPS):
        return "`git rebase` may only go on with a rebase portkey started (--continue, --abort, --skip)."
    return None


def _start_in(segments, worktree):
    """(the segments to judge, the folder redirects resolve in, why the command doesn't start in the worktree)."""
    move = f"start the command with `cd {shlex.quote(str(worktree))} &&` or use `git -C {worktree}`"
    first = segments[0].words if segments else ()
    if first[:1] == ("cd",):
        if len(first) != 2 or not same_dir(first[1], worktree) or segments[0].operator != "&&":
            return segments, None, f"{move}."
        rest = segments[1:]
        if any(program_part(segment.words)[:1] in (["cd"], ["pushd"], ["popd"]) for segment in rest):
            return rest, None, f"a second `cd` leaves {worktree}; {move}."
        return rest, worktree, None
    commands = [segment.words for segment in segments if segment.words]
    if commands and all(_is_git_c(words, worktree) for words in commands):
        return segments, None, None
    return segments, None, f"{move}."


def _is_git_c(words, worktree):
    words = program_part(words)
    return len(words) > 2 and words[:2] == ["git", "-C"] and same_dir(words[2], worktree)


def _redirects(command, base):
    """Output redirects must land inside `base`; without one (no `cd` first), only /dev/null and fd copies."""
    tokens = shellwords.tokens(command)
    for token, following in zip(tokens, tokens[1:]):
        if token.kind != "op" or ">" not in token.value or following.kind != "word":
            continue
        target = following.value
        if target == "/dev/null" or (token.value.endswith("&") and target.isdigit()):
            continue
        if base is None or not in_worktree(resolve(target, base), base):
            where = f"outside {base} (or into its .git)" if base else "where curfew can't see (start with cd)"
            return f"`{token.value} {target}` writes {where}."
    return None


def resolve(word, cwd):
    """Where a shell word points, symlinks resolved; a glob is judged by its folder; None when unknowable."""
    expanded = shellpaths.expand(word, str(cwd))
    if shellpaths.UNRESOLVABLE.search(expanded):
        return None
    if GLOB_CHARS & set(os.path.basename(expanded)):
        expanded = os.path.dirname(expanded) or "."
    try:
        return pathlib.Path(os.path.realpath(os.path.join(cwd, expanded)))
    except (OSError, ValueError):
        return None


def in_worktree(path, worktree):
    """True when `path` is inside the worktree and not in or at its `.git`."""
    if path is None:
        return False
    try:
        real = pathlib.Path(os.path.realpath(worktree))
        return path.is_relative_to(real) and ".git" not in path.relative_to(real).parts
    except (OSError, ValueError):
        return False


def same_dir(word, folder):
    """True when an absolute path names `folder` (the agent's own folder is the main checkout, so a relative one
    never does)."""
    if not os.path.isabs(shellpaths.expand(word, str(folder))):
        return False
    return resolve(word, folder) == pathlib.Path(os.path.realpath(folder))
