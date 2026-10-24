"""Load `.accio/config.json` over the defaults in DESIGN § 5.2, and check every value."""
import json

from accio_lib.frozen import freeze

CONFIG_NAME = "config.json"
PUSH_MODES = ("direct",)  # "pr" comes in v2 (decision 009)

DEFAULTS = freeze({
    "base_branch": "main",
    "push_mode": "direct",
    "checks": [],
    "risky_paths": ["**/auth/**", "**/payments/**", "**/migrations/**", "**/*secret*", ".github/workflows/**"],
    "budgets": {"quick": 80000, "story": 400000},
    "wip": 3,
    "iteration_max": 8,
    "stack_depth": 2,
    "agent_allow": [],
    "paid_call_cap_usd": 0,
    "mutation": None,
    "snapshot_skip": [],
    "preview": None,
    "breaker": None,
    "ui_globs": [],
    "ui_evidence": None,
})


class ConfigError(Exception):
    """A config problem, written for the user."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(value):
    return None if _is_int(value) and value >= 1 else "must be a whole number, 1 or more"


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _check_checks(value):
    if not isinstance(value, list):
        return "must be a list of {command, glob} objects"
    for check in value:
        if not isinstance(check, dict) or not all(
            isinstance(check.get(key), str) and check[key].strip() for key in ("command", "glob")
        ):
            return f"each check needs a non-empty command and glob, got {check!r}"
    return None


def _check_budgets(value):
    if not isinstance(value, dict):
        return "must be an object like {\"quick\": 80000, \"story\": 400000}"
    unknown = set(value) - set(DEFAULTS["budgets"])
    if unknown:
        return f"has unknown tracks: {', '.join(sorted(unknown))}"
    if not all(_is_int(amount) and amount > 0 for amount in value.values()):
        return "values must be positive whole numbers of tokens"
    return None


def _check_mutation(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"command"} or not isinstance(value["command"], str):
        return 'must be {"command": "<the mutation tool, with {diff} where the story\'s diff file goes>"}'
    return None if "{diff}" in value["command"] else "command must contain {diff}, where the story's diff file goes"


def _check_breaker(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"command"} or not isinstance(value["command"], str):
        return 'must be {"command": "<runs one repro file, with {file} where its path goes>"}'
    return None if "{file}" in value["command"] else "command must contain {file}, where the repro's path goes"


PREVIEW_KEYS = {"command", "url", "test_data", "login", "env", "mcp_prefix"}
LOGIN_KEYS = {"username_env", "password_env"}


def _check_login(login):
    shape = 'login must be {"username_env": "<variable name>", "password_env": "<variable name>"}'
    if not isinstance(login, dict):
        return shape
    values = sorted(set(login) & {"username", "password"})
    if values:
        return (f"login must not hold a {' or '.join(values)} value; name the environment variables that hold "
                f"them: {shape}")
    if set(login) != LOGIN_KEYS or not all(isinstance(name, str) and name.strip() for name in login.values()):
        return shape
    return None


def _check_preview(value):
    if value is None:
        return None
    shape = 'must be {"command": "<starts the app>", "url": "http://...", "test_data": true}'
    if not isinstance(value, dict) or not {"command", "url"} <= set(value) or set(value) - PREVIEW_KEYS:
        return shape
    if not all(isinstance(value[key], str) and value[key].strip() for key in ("command", "url")):
        return shape
    if not value["url"].startswith(("http://", "https://")):
        return "url must start with http:// or https://"
    if "test_data" in value and not isinstance(value["test_data"], bool):
        return "test_data must be true or false"
    prefix = value.get("mcp_prefix", "x")
    if not isinstance(prefix, str) or not prefix.strip():
        return "mcp_prefix must be the browser tools' name prefix, like mcp__plugin_playwright_playwright__"
    env = value.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str)
                                            for k, v in env.items()):
        return 'env must be an object of variable names and string values, like {"PORT": "3000"}'
    problem = _check_login(value["login"]) if "login" in value else None
    return f"preview {problem}" if problem else None


EVIDENCE_REQUIRED = ("command", "steps_doc", "takes_over_screen")
EVIDENCE_KEYS = {*EVIDENCE_REQUIRED, "themes", "timeout"}
EVIDENCE_PLACEHOLDERS = ("{steps}", "{folder}")
PREFECT_BASH_LIMIT = 600  # seconds: prefect runs the evidence command, and its Bash tool stops there
EVIDENCE_TIMEOUT_MAX = 540  # the default too: the command stops first, so its own note reaches the build (S-070)


def _check_steps_doc(value):
    if not isinstance(value, str) or not value.strip():
        return "steps_doc must be the repo file that documents the steps, like docs/ui-walk.md"
    if value.startswith("/") or ".." in value.split("/"):
        return "steps_doc must be a path inside the repo, like docs/ui-walk.md"
    return None


def _check_evidence_values(value):
    command = value["command"]
    if not isinstance(command, str) or not command.strip():
        return "command must be the command that makes the screenshots, with {steps} and {folder}"
    missing = [mark for mark in EVIDENCE_PLACEHOLDERS if mark not in command]
    if missing:
        return f"command must contain {' and '.join(missing)}: accio fills in the steps file and the evidence folder"
    if not isinstance(value["takes_over_screen"], bool):
        return "takes_over_screen must be true or false"
    if "themes" in value and not _strings(value["themes"]):
        return 'themes must be a list of theme names, like ["light", "dark"]'
    if "timeout" in value and _positive_int(value["timeout"]):
        return "timeout must be a whole number of seconds, 1 or more"
    if "timeout" in value and value["timeout"] > EVIDENCE_TIMEOUT_MAX:
        return (f"timeout must be {EVIDENCE_TIMEOUT_MAX} seconds or less: prefect runs the command, and its Bash tool "
                f"stops at {PREFECT_BASH_LIMIT}")
    return _check_steps_doc(value["steps_doc"])


def _check_ui_evidence(value):
    if value is None:
        return None
    shape = ('must be {"command": "<makes screenshots, with {steps} and {folder}>", "steps_doc": "<repo file>", '
             '"takes_over_screen": false}')
    if not isinstance(value, dict):
        return shape
    unknown = sorted(set(value) - EVIDENCE_KEYS)
    if unknown:
        return f"has unknown keys {', '.join(unknown)}; known keys are {', '.join(sorted(EVIDENCE_KEYS))}"
    missing = [key for key in EVIDENCE_REQUIRED if key not in value]
    if missing:
        return f"lacks {', '.join(missing)}: it {shape}"
    return _check_evidence_values(value)


CHECKERS = {
    "base_branch": lambda v: None if isinstance(v, str) and v.strip() else "must be a branch name",
    "push_mode": lambda v: None if v in PUSH_MODES else f"must be one of {', '.join(PUSH_MODES)} (\"pr\" comes in v2)",
    "checks": _check_checks,
    "risky_paths": lambda v: None if _strings(v) else "must be a list of glob strings",
    "budgets": _check_budgets,
    "wip": _positive_int,
    "iteration_max": _positive_int,
    "stack_depth": _positive_int,
    "agent_allow": lambda v: None if _strings(v) else "must be a list of command strings",
    "paid_call_cap_usd": lambda v: None if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
    else "must be a number, 0 or more",
    "mutation": _check_mutation,
    "snapshot_skip": lambda v: None if _strings(v) else "must be a list of glob strings",
    "preview": _check_preview,
    "breaker": _check_breaker,
    "ui_globs": lambda v: None if _strings(v) else "must be a list of glob strings",
    "ui_evidence": _check_ui_evidence,
}


def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path} cannot be read: {error}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object")
    return data


def load(accio_dir):
    """The config with defaults filled in, as read-only data. Raises ConfigError naming the bad key."""
    path = accio_dir / CONFIG_NAME
    data = _read(path)
    unknown = sorted(set(data) - set(CHECKERS))
    if unknown:
        raise ConfigError(f"{path}: unknown key {', '.join(unknown)}; known keys are {', '.join(CHECKERS)}")
    for key, value in data.items():
        problem = CHECKERS[key](value)
        if problem:
            raise ConfigError(f"{path}: {key} {problem}")
    if data.get("preview") is not None and data.get("ui_evidence") is not None:
        raise ConfigError(f"{path}: preview and ui_evidence are both set; set one (preview for a web app, "
                          "ui_evidence for a native app)")
    budgets = {**DEFAULTS["budgets"], **data.get("budgets", {})}
    return freeze({**DEFAULTS, **data, "budgets": budgets})
