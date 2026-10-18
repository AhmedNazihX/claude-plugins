"""The `ask` rules in Claude Code's settings that would freeze a build (DESIGN § 4.4; spike S-015).

Inside a workflow agent, a settings `ask` rule shows a question no one answers, and the agent waits for ever; no
hook answer can lift it once it is asked. A hook's `deny` beats a rule's `ask`, so `curfew` denies an accio agent's
call that matches one, and `accio-hooks verify` lists them.

Rules are read from the user's, the project's, the local and the managed settings. A rule without a specifier
(`Edit`) matches every call of that tool; `mcp__server` matches all of that server's tools. A `Bash(…)` specifier
matches the whole command or any simple command in it: `prefix:*` by prefix, a `*` as a wildcard, anything else
exactly. Any other specifier (a path, a domain) is matched loosely, by its tool alone: a call it might cover is
denied rather than left to freeze. A settings file that can't be read is skipped.
"""
import dataclasses
import fnmatch
import json
import pathlib
import re

from accio_lib import shellwords

MANAGED_SETTINGS = (pathlib.Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
                    pathlib.Path("/etc/claude-code/managed-settings.json"))
RULE = re.compile(r"^(?P<tool>[A-Za-z_][\w-]*)(?:\((?P<spec>.*)\))?$", re.S)


@dataclasses.dataclass(frozen=True)
class Rule:
    text: str
    source: pathlib.Path


def settings_files(root, home):
    return (home / ".claude" / "settings.json", root / ".claude" / "settings.json",
            root / ".claude" / "settings.local.json", *MANAGED_SETTINGS)


def _rules_in(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    asks = data.get("permissions", {}).get("ask", []) if isinstance(data, dict) else []
    if not isinstance(asks, list):
        return ()
    return tuple(Rule(text, path) for text in asks if isinstance(text, str) and text.strip())


def ask_rules(root, home):
    """Every `ask` rule in the settings that apply to a session in `root`."""
    return tuple(rule for path in settings_files(root, home) for rule in _rules_in(path))


def _bash_matches(spec, command):
    if spec.endswith(":*"):
        prefix = spec[:-2]
        return command == prefix or command.startswith(prefix + " ")
    if "*" in spec:
        return fnmatch.fnmatchcase(command, spec)
    return command == spec


def _commands(command):
    simple = (" ".join(segment.words) for segment in shellwords.segments(command) if segment.words)
    return (command.strip(), *simple)


def matches(rule_text, tool, tool_input):
    """True when this rule would ask about this call."""
    parsed = RULE.match(rule_text.strip())
    if not parsed:
        return False
    rule_tool, spec = parsed.group("tool"), parsed.group("spec")
    if rule_tool != tool and not (rule_tool.startswith("mcp__") and tool.startswith(rule_tool + "__")):
        return False
    if spec is None or spec.strip() in ("", "*") or tool != "Bash":
        return True
    command = tool_input.get("command") if isinstance(tool_input.get("command"), str) else ""
    return any(_bash_matches(spec.strip(), text) for text in _commands(command))


def first_match(rules, tool, tool_input):
    return next((rule for rule in rules if matches(rule.text, tool, tool_input)), None)
