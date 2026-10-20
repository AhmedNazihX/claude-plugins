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


def _check_preview(value):
    if value is None:
        return None
    shape = 'must be {"command": "<starts the app>", "url": "http://..."}'
    if not isinstance(value, dict) or set(value) != {"command", "url"}:
        return shape
    if not all(isinstance(value[key], str) and value[key].strip() for key in value):
        return shape
    return None if value["url"].startswith(("http://", "https://")) else "url must start with http:// or https://"


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
    budgets = {**DEFAULTS["budgets"], **data.get("budgets", {})}
    return freeze({**DEFAULTS, **data, "budgets": budgets})
