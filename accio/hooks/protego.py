#!/usr/bin/env python3
"""protego: the PreToolUse Bash guard (DESIGN § 4.4, decision 004).

An early warning, not the wall (the native git hooks are): it blocks a short list and names the safe alternative.
- always: `--no-verify` (and `git commit -n`, `HUSKY=0`), changing `core.hooksPath`, and unsetting `CLAUDECODE`,
  which accio's own git hooks depend on
- unless dcg is running as a Claude Code hook (it guards these better, so protego defers; dcg on PATH but not set
  up as a PreToolUse hook doesn't count): `git reset --hard`, `git clean -f`,
  `git branch -D`, and `rm -rf` of anything outside the repo and its story worktrees (or of the repo or `.git`)

The command is split the way bash reads it (`accio_lib.shellwords`); leading `VAR=value`, `env`, wrappers like
`sudo` and reserved words like `{`, `then` or `!` are looked through; `cd`/`pushd` move the folder later parts are
judged in (a subshell's `cd` stays inside it; `accio_lib.shellpaths` says where each `rm` target points). Commands
inside `$(…)` and backticks, `sh -c '…'`, `eval '…'` and a heredoc or here-string fed to a shell are checked too;
git's shortened long options count. `rm -rf` may also clean temp scratch away from the repo. Wrapping a command
further (a pipe into `sh`, an alias) is an accepted bypass (decision 004). Exits 0 silently in a repo without
`.accio/`, for other tools and on bad input.
"""
import dataclasses
import json
import os
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

from accio_lib import paths, shellpaths, shellwords  # noqa: E402

BLOCK_EXIT = 2
MAX_DEPTH = 3
ASSIGNMENT = shellpaths.ASSIGNMENT
RESERVED = {"{", "}", "!", "if", "then", "elif", "else", "do", "while", "until", "coproc"}
WRAPPERS = {"sudo", "command", "builtin", "exec", "nohup", "time", "nice", "xargs"}
WRAPPER_OPTIONS_WITH_VALUE = {"-u", "-g", "-n", "-C", "-p"}
SHELLS = {"sh", "bash", "zsh", "dash"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
COMMIT_SHORT_WITH_VALUE = set("mFCct")
COMMIT_SHORT_ATTACHED_VALUE = set("uS")  # `-uno`, `-S<key>`: the value never takes the next word
COMMIT_LONG_WITH_VALUE = {"--message", "--file", "--author", "--date", "--template", "--reuse-message",
                          "--reedit-message", "--fixup", "--squash", "--trailer", "--cleanup"}
CONFIG_WRITES = {"set", "unset", "--unset", "--unset-all", "--replace-all", "--add"}
DECLARERS = {"export", "declare", "typeset", "readonly", "local"}
ENV_CLEARS = {"-", "--ignore-environment"}
GUARD_VAR = "CLAUDECODE"
GIT_CONFIG_VARS = re.compile(r"^GIT_CONFIG_(PARAMETERS|KEY_\d+)$")
CD_COMMANDS = {"cd", "pushd"}
CLEAN_FORCE_OFF = re.compile(r"^clean\.requireforce=(false|no|off|0)$", re.I)
PROJECT_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")
DCG_COMMAND = re.compile(r"(?:^|[\s/\"'])dcg(?:$|[\s\"'])")
BASH_MATCHERS = ("", "*")

RESET = ("`git reset --hard` throws away uncommitted work. Instead: `git stash` to set it aside, or "
         "`git restore <file>` for one file.")
CLEAN = ("`git clean -f` deletes untracked files for good. Instead: `git clean -n` lists them; then remove the ones "
         "you mean by name.")
BRANCH = ("`git branch -D` deletes a branch even when it isn't merged. Instead: `git branch -d <branch>`, which git "
          "refuses while the branch has unmerged work.")
RM = ("`rm -rf {targets}` reaches outside this repo, or removes the repo or its .git. Instead: delete only paths "
      "inside the repo, by name.")
NO_VERIFY = ("skipping git hooks (`--no-verify`, `git commit -n`) also skips accio's secret scan and push guard. "
             "Instead: fix what the hook reports, then run the command normally.")
HUSKY_OFF = ("`HUSKY=0` turns off the project's git hooks, accio's included. Instead: fix what the hook reports, "
             "then run the command normally.")
HOOKS_PATH = ("changing `core.hooksPath` points git away from accio's hooks. Instead: use `accio-hooks install` or "
              "`accio-hooks uninstall`.")
TOO_DEEP = (f"this command nests commands more than {MAX_DEPTH} levels deep, too deep to check. Instead: run the inner "
            "commands directly.")
GUARD = (f"unsetting `{GUARD_VAR}` hides that Claude is running the command, and accio's push guard needs it to "
         "tell Claude's pushes from yours. Instead: keep it set; to push yourself, use your own terminal.")


@dataclasses.dataclass(frozen=True)
class Call:
    assigns: dict
    unsets: frozenset
    argv: tuple


@dataclasses.dataclass(frozen=True)
class Scope:
    """What every part of one command is judged against."""
    root: pathlib.Path
    generic: bool  # False when dcg runs as a hook and takes the generic list
    assigned: frozenset = frozenset()  # variables the command sets, so their values are unknowable


@dataclasses.dataclass(frozen=True)
class GitCall:
    config: tuple
    sub: str
    rest: tuple


# --- reading a command ------------------------------------------------------------------------------------------

def _words(script):
    return [word for segment in shellwords.segments(script) for word in segment.words]


def _env_options(tokens):
    """(the tokens after env's options, the names env unsets; `-i` clears them all, CLAUDECODE included)."""
    unsets, index = set(), 0
    while index < len(tokens) and tokens[index].startswith("-"):
        token = tokens[index]
        if token in ("-u", "--unset") and index + 1 < len(tokens):
            unsets.add(tokens[index + 1])
            index += 1
        elif token.startswith("--unset="):
            unsets.add(token.split("=", 1)[1])
        elif token.startswith("-u") and len(token) > 2:
            unsets.add(token[2:])
        elif token in ("-S", "--split-string") and index + 1 < len(tokens):
            return [*_words(tokens[index + 1]), *tokens[index + 2:]], unsets
        elif token.startswith("--split-string=") or (token.startswith("-S") and len(token) > 2):
            script = token.split("=", 1)[1] if token.startswith("--") else token[2:]
            return [*_words(script), *tokens[index + 1:]], unsets
        elif token in ENV_CLEARS or (not token.startswith("--") and "i" in token[1:]):
            unsets.add(GUARD_VAR)
        index += 1
    return tokens[index:], unsets


def _skip_options(tokens):
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in WRAPPER_OPTIONS_WITH_VALUE else 1
    return tokens[index:]


def _call(tokens):
    """Look through leading assignments, `env` and wrappers to the command that actually runs."""
    assigns, unsets, rest = {}, set(), list(tokens)
    while rest:
        name = os.path.basename(rest[0])
        if ASSIGNMENT.match(rest[0]):
            key, _, value = rest[0].partition("=")
            assigns = {**assigns, key: value}
            unsets -= {GUARD_VAR} if (key, value) == (GUARD_VAR, "1") else set()
            rest = rest[1:]
        elif name == "env":
            rest, removed = _env_options(rest[1:])
            unsets |= removed
        elif name in WRAPPERS:
            rest = _skip_options(rest[1:])
        elif rest[0] in RESERVED:
            rest = rest[1:]
        else:
            break
    return Call(assigns, frozenset(unsets), tuple(rest))


def _git_call(argv):
    if not argv or os.path.basename(argv[0]) != "git":
        return None
    config, index = [], 1
    while index < len(argv) and argv[index].startswith("-"):
        option = argv[index]
        if option == "-c" and index + 1 < len(argv):
            config.append(argv[index + 1])
        elif option.startswith("--config-env="):
            config.append(option.split("=", 1)[1])
        index += 2 if option in GIT_OPTIONS_WITH_VALUE else 1
    return GitCall(tuple(config), argv[index], tuple(argv[index + 1:])) if index < len(argv) else None


def _short_flags(tokens):
    return {letter for token in tokens if token.startswith("-") and not token.startswith("--") for letter in token[1:]}


def _has_long(tokens, option, shortest):
    """git accepts any unambiguous start of a long option: `--no-ver` is `--no-verify`."""
    return any(token.startswith(shortest) and option.startswith(token) for token in tokens)


def _declared(call):
    """NAME=value pairs set for the command: its leading assignments, or the arguments of `export` and kin."""
    if not call.argv or call.argv[0] not in DECLARERS:
        return call.assigns
    pairs = (arg.partition("=") for arg in call.argv[1:] if ASSIGNMENT.match(arg))
    return {**call.assigns, **{key: value for key, _, value in pairs}}


# --- the rules --------------------------------------------------------------------------------------------------

def _unsets_guard(call):
    if GUARD_VAR in call.unsets or _declared(call).get(GUARD_VAR, "1") != "1":
        return GUARD
    name, args = (call.argv[0], call.argv[1:]) if call.argv else ("", ())
    if name == "unset" and GUARD_VAR in args:
        return GUARD
    if name in DECLARERS and GUARD_VAR in args and ("-n" in args or "+x" in args):
        return GUARD
    return None


def _commit_skips_hooks(rest):
    skip_next = False
    for token in rest:
        if skip_next:
            skip_next = False
        elif token == "--":
            return False
        elif token in COMMIT_LONG_WITH_VALUE:
            skip_next = True
        elif token.startswith("-") and not token.startswith("--"):
            for index, letter in enumerate(token[1:]):
                if letter == "n":
                    return True
                if letter in COMMIT_SHORT_ATTACHED_VALUE:
                    break
                if letter in COMMIT_SHORT_WITH_VALUE:
                    skip_next = index == len(token) - 2
                    break
    return False


def _sets_hooks_path(rest):
    keys = [index for index, token in enumerate(rest) if token.lower() == "core.hookspath"]
    if not keys:
        return False
    after = [token for token in rest[keys[0] + 1:] if not token.startswith("-")]
    return bool(after) or any(token in CONFIG_WRITES for token in rest[:keys[0]])


def _hook_bypass(call):
    declared, git = _declared(call), _git_call(call.argv)
    if any(GIT_CONFIG_VARS.match(name) and "core.hookspath" in value.lower() for name, value in declared.items()):
        return HOOKS_PATH
    is_export = bool(call.argv) and call.argv[0] in DECLARERS
    if declared.get("HUSKY") == "0" and (git is not None or is_export):
        return HUSKY_OFF
    if git is None:
        return None
    if any(value.lower().startswith("core.hookspath") for value in git.config):
        return HOOKS_PATH
    if git.sub == "config" and _sets_hooks_path(git.rest):
        return HOOKS_PATH
    if _has_long(git.rest, "--no-verify", "--no-v") or (git.sub == "commit" and _commit_skips_hooks(git.rest)):
        return NO_VERIFY
    return None


def _clean_deletes(rest, require_force=True):
    """`git clean` forced (or with `clean.requireForce` off) and not a dry run, reading past `-e <pattern>` values
    (`-fen` excludes "n"; `--exc` is `--exclude`)."""
    letters, longs, skip_next = set(), [], False
    for token in rest:
        if skip_next:
            skip_next = False
        elif token == "--":
            break
        elif token == "-e" or (token.startswith("--e") and "--exclude".startswith(token)):
            skip_next = True
        elif token.startswith("--"):
            longs.append(token)
        elif token.startswith("-"):
            cluster = token[1:].split("e", 1)
            letters |= set(cluster[0])
            skip_next = len(cluster) == 2 and not cluster[1]
    forced = "f" in letters or _has_long(longs, "--force", "--fo") or not require_force
    return forced and not ("n" in letters or _has_long(longs, "--dry-run", "--dr"))


def _git_destructive(call):
    git = _git_call(call.argv)
    if git is None:
        return None
    flags, rest = _short_flags(git.rest), git.rest
    forced = "f" in flags or _has_long(rest, "--force", "--fo")
    if git.sub == "reset" and _has_long(rest, "--hard", "--ha"):
        return RESET
    require_force = not any(CLEAN_FORCE_OFF.match(value.replace(" ", "")) for value in git.config)
    if git.sub == "clean" and _clean_deletes(rest, require_force):
        return CLEAN
    deletes = "d" in flags or _has_long(rest, "--delete", "--de")
    if git.sub == "branch" and ("D" in flags or deletes and forced):
        return BRANCH
    return None


def _rm_outside(call, cwd, scope):
    if not call.argv or os.path.basename(call.argv[0]) != "rm":
        return None
    options = [token for token in call.argv[1:] if token.startswith("-") and token != "-"]
    if "--" in options:
        options = options[:options.index("--")]
    flags = _short_flags(options) | ({"r"} if _has_long(options, "--recursive", "--r") else set()) | \
        ({"f"} if _has_long(options, "--force", "--f") else set())
    if not ({"r", "R"} & flags and "f" in flags):
        return None
    targets = [token for token in call.argv[1:] if token not in options and token != "--"]
    outside = [alternative for target in targets for alternative in shellpaths.brace_alternatives(target)
               if not shellpaths.deletable(alternative, cwd, scope.root, scope.assigned)]
    return RM.format(targets=" ".join(outside)) if outside else None


# --- the hook ---------------------------------------------------------------------------------------------------

def _inner_command(argv):
    """The script of `sh -c '…'` (or `bash -lc`), or None."""
    flag = next((index for index, token in enumerate(argv[1:], 1)
                 if token.startswith("-") and not token.startswith("--") and "c" in token), None)
    return argv[flag + 1] if flag is not None and flag + 1 < len(argv) else None


def check_command(command, cwd, scope, depth=0):
    """The block message for the first part of `command` on the list, or None."""
    segments = tuple(shellwords.segments(command))
    scope = dataclasses.replace(scope, assigned=scope.assigned | shellpaths.assigned_names(s.words for s in segments))
    inners = shellwords.substitutions(command)
    if inners and depth >= MAX_DEPTH:
        return TOO_DEEP
    for inner in inners:
        reason = check_command(inner, cwd, scope, depth + 1)
        if reason:
            return reason
    outer, in_case = [], 0  # outer: the folder to return to when each open subshell closes
    for segment in segments:
        call = _call(segment.words)
        name = os.path.basename(call.argv[0]) if call.argv else ""
        reason = None
        if name == "case":
            in_case += 1
        elif name == "esac":
            in_case = max(0, in_case - 1)
        elif name in CD_COMMANDS:
            cwd = shellpaths.cd(cwd, call.argv, scope.root, scope.assigned)
        elif name == "popd":
            cwd = None
        else:
            reason = _check_call(call, name, segment, cwd, scope, depth)
        if reason:
            return reason
        if in_case:  # a case pattern's `(`/`)` are not subshells
            continue
        if segment.operator == "(":
            outer.append(cwd)
        elif segment.operator == ")" and outer:
            cwd = outer.pop()
    return None


def _scripts_run(call, name, segment):
    """The text a shell or `eval` runs as commands: `sh -c '…'`, a heredoc or here-string fed to a shell, `eval`."""
    if name == "eval":
        return (" ".join(call.argv[1:]),)
    if name not in SHELLS:
        return ()
    script = _inner_command(call.argv)
    return (script,) if script is not None else segment.inputs


def _check_call(call, name, segment, cwd, scope, depth):
    scripts = _scripts_run(call, name, segment)
    if scripts and depth >= MAX_DEPTH:
        return TOO_DEEP
    for script in scripts:
        reason = check_command(script, cwd, scope, depth + 1)
        if reason:
            return reason
    reason = _unsets_guard(call) or _hook_bypass(call)
    if not reason and scope.generic:
        reason = _git_destructive(call) or _rm_outside(call, cwd, scope)
    return reason


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hooks_dcg_on_bash(settings):
    hooks = settings.get("hooks")
    entries = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    for entry in entries if isinstance(entries, list) else ():
        matcher = entry.get("matcher", "") if isinstance(entry, dict) else None
        if not isinstance(matcher, str) or not (matcher in BASH_MATCHERS or "Bash" in matcher):
            continue
        hooks_run = entry.get("hooks")
        commands = [hook.get("command") for hook in hooks_run if isinstance(hook, dict)] \
            if isinstance(hooks_run, list) else []
        if any(isinstance(command, str) and DCG_COMMAND.search(command) for command in commands):
            return True
    return False


def dcg_is_active(root):
    """dcg guards Bash only when it is on PATH and set up as a PreToolUse hook in the user's or project's settings."""
    if shutil.which("dcg") is None:
        return False
    files = (pathlib.Path.home() / ".claude" / "settings.json", *(root / name for name in PROJECT_SETTINGS))
    settings = [_read_json(path) for path in files]
    if any(entry.get("disableAllHooks") is True for entry in settings):
        return False
    return any(_hooks_dcg_on_bash(entry) for entry in settings)


def _command_and_cwd(raw):
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None, None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    try:
        return (command, os.path.realpath(cwd)) if isinstance(command, str) else (None, None)
    except (ValueError, OSError):  # a NUL or an unreadable folder: not a repo this hook can judge
        return None, None


def main():
    command, cwd = _command_and_cwd(sys.stdin.read())
    if command is None or paths.accio_dir(cwd) is None:
        return 0
    try:
        root = paths.main_root(cwd)
        reason = check_command(command, cwd, Scope(root, generic=not dcg_is_active(root)))
    except Exception as error:  # noqa: BLE001  (in an accio repo a guard that fails blocks, never lets it through)
        reason = f"couldn't check this command ({type(error).__name__}), so it is blocked"
    if reason:
        print(f"protego: {reason}", file=sys.stderr)
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
