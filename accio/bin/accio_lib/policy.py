"""curfew's policy: what each accio agent may do (DESIGN § 4.4, § 6; decision 010; spike S-015).

Every call by an accio agent gets an answer, so none waits on a permission question. Read tools and the reply tools
are allowed for every accio agent (house-elf before its claim too): a reply only goes back to the agent's caller,
and denying it loses the agent's result. Beyond that each agent has an exact list (AGENTS), and anything off it is
denied with the reason, which in a build becomes a BLOCKED question at `owl`. No list lets an agent write `run/push-ok` or `run/brew.lock`.

`house-elf` first runs `accio-claim <ID>` on its own (accio's own script, nothing else in the command) for a story
in progress (`doing` in `run/status.json`) that no other agent holds. That links its `agent_id` to the story's
worktree; the story's next `accio-brief` (a fix round) releases the claim. Until it claims, it may only read.
After the claim it writes only inside its worktree (never its `.git`) and its `.accio/run/<ID>/build-report.md`,
symlinks and `..` resolved, and its Bash commands follow `bashpolicy`: they start in the worktree, and run the
checks, `agent_allow`, read-only tools, file tools in the worktree and a short list of git subcommands. The other
agents run only the accio scripts and subcommands their step needs (SCRIPTS).
"""
import dataclasses
import fnmatch
import os
import pathlib
import re
import shlex

from accio_lib import bashpolicy, paths, shellwords, story, summary

READ_TOOLS = frozenset({"Read", "Grep", "Glob", "LS"})
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
WEB_TOOLS = frozenset({"WebSearch", "WebFetch"})
REPLY_TOOLS = frozenset({"SubagentHandback", "StructuredOutput"})  # a background reply; a workflow's schema reply
CLAIM_SCRIPT = "accio-claim"
REPORT_NAME = summary.REPORT_NAME
BOARD_RUN = frozenset({"ready", "status", "lock", "unlock", "move", "refresh"})
LEDGER_USE = frozenset({"key", "check", "record"})
SCRIPTS = {  # each Bash policy's accio scripts and the subcommands it may run (None: any)
    "scripts": {"accio-board": BOARD_RUN, "accio-brief": None, "accio-hooks": frozenset({"verify"}),
                "accio-check": None, "accio-preview": frozenset({"start", "stop"})},
    "checks": {"accio-ledger": LEDGER_USE, "accio-board": frozenset({"move", "refresh"}), "accio-check": None},
    "ledger": {"accio-ledger": frozenset({"key", "check"})},  # headmaster reads; prefect records the outcome (S-020)
}
PREFECT_CHECK = re.compile(r"S-\d{3,}")  # prefect runs exactly `accio-check <ID>`; only portkey takes snapshots
IN_PROGRESS = "doing"


@dataclasses.dataclass(frozen=True)
class Lists:
    """An agent's exact list: `writes` are globs under `.accio/`; `bash` names its command policy."""
    web: bool = False
    writes: tuple = ()
    bash: str = ""  # "scripts" (portkey), "checks" (prefect), "ledger" (headmaster)


AGENTS = {
    "portkey": Lists(bash="scripts"),
    "prefect": Lists(writes=("run/questions/*.md",), bash="checks"),
    "examiner": Lists(writes=("run/*/*-findings.md",)),
    "professor": Lists(writes=("run/*/*-findings.md",)),
    "auror": Lists(writes=("run/*/*-findings.md",)),
    "headmaster": Lists(writes=("run/questions/*.md", "run/*/ruling-r[0-9]*.md"), bash="ledger"),
    "seeker": Lists(web=True, writes=("run/wand/seeker-notes.md",)),
    "wandmaker": Lists(writes=("run/wand/wandmaker-options.md",)),
    "quill": Lists(writes=("stories/S-*.md", "run/sort/quill-summary.md")),
    "librarian": Lists(),
    "howler": Lists(bash="howler"),
}

HEX_SHA = r"[0-9a-f]{40}"
NUMBER = r"[0-9]+"  # ASCII digits only (`\d` would take other scripts' digits)
WORD = r"[A-Za-z0-9._/][A-Za-z0-9._/-]*"  # a branch, or a git word such as HEAD or origin; never starts with `-`
RUN_JSON_FIELDS = frozenset({"databaseId", "workflowDatabaseId", "headSha", "headBranch", "status", "conclusion",
                             "name", "jobs"})
HOWLER_FORMS = (  # howler reads CI runs and compares commits; each is one exact shape (S-001)
    bashpolicy.Form(("gh", "run", "list"), flags={"--commit": HEX_SHA, "--workflow": NUMBER,
                                                  "--branch": WORD, "--limit": NUMBER},
                    json_fields=RUN_JSON_FIELDS),
    bashpolicy.Form(("gh", "run", "watch"), operands=(NUMBER,), flags={"--exit-status": None, "--compact": None}),
    bashpolicy.Form(("gh", "run", "view"), operands=(NUMBER,), flags={"--log-failed": None, "--job": NUMBER},
                    json_fields=RUN_JSON_FIELDS),
    bashpolicy.Form(("git", "merge-base", "--is-ancestor"), operands=(HEX_SHA, HEX_SHA)),
    bashpolicy.Form(("git", "diff", "--name-only"), operands=(HEX_SHA, HEX_SHA)),
    bashpolicy.Form(("git", "rev-parse"), operands=(WORD,)),
    bashpolicy.Form(("git", "remote", "get-url"), operands=(WORD,)),
    bashpolicy.Form(("tail", "-60")),  # the end of a failed job's log; bashpolicy allows it only after a pipe
)


@dataclasses.dataclass(frozen=True)
class Context:
    root: pathlib.Path      # the main checkout
    accio: pathlib.Path     # its .accio/
    bin_dir: pathlib.Path   # accio's scripts
    config: dict
    claims: dict            # agent_id -> {"story", "worktree"}
    statuses: dict          # story -> status, from run/status.json


@dataclasses.dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
    claim: tuple = None     # (story, worktree) when this call is a claim to record


def allow():
    return Decision(True)


def deny(reason):
    return Decision(False, reason)


def decide(agent, agent_id, tool, tool_input, ctx):
    """The answer for one call by `accio:<agent>`."""
    if tool in REPLY_TOOLS and (agent == "house-elf" or agent in AGENTS):
        return allow()
    if agent == "house-elf":
        return _house_elf(agent_id, tool, tool_input, ctx)
    lists = AGENTS.get(agent)
    if lists is None:
        return deny(f"accio:{agent} isn't one of accio's agents, so curfew allows it nothing.")
    if tool in READ_TOOLS or (tool in WEB_TOOLS and lists.web):
        return allow()
    if tool in WRITE_TOOLS:
        target = _target(tool_input)
        if target and any(_under(target, ctx.accio, pattern) for pattern in lists.writes):
            return allow()
        where = ", ".join(f".accio/{pattern}" for pattern in lists.writes) or "nowhere"
        return deny(f"accio:{agent} may write only to {where}, not {target or 'this file'}.")
    if tool == "Bash" and lists.bash:
        return _verdict(bashpolicy.check(_command(tool_input), _other_judge(agent, lists.bash, ctx)))
    return deny(f"{tool} isn't on accio:{agent}'s list.")


def _verdict(reason):
    return deny(reason) if reason else allow()


# --- house-elf ---------------------------------------------------------------------------------------------------

def _house_elf(agent_id, tool, tool_input, ctx):
    claim = ctx.claims.get(agent_id)
    if tool == "Bash":
        request = _claim_request(_command(tool_input), ctx)
        if request is not None:
            return _claim(request, claim, ctx)
    if tool in READ_TOOLS:
        return allow()
    if claim is None:
        return deny("house-elf first runs `accio-claim <ID>` (the command in its brief); until then it may only read.")
    worktree = pathlib.Path(claim["worktree"])
    if tool in WRITE_TOOLS:
        return _house_elf_write(_target(tool_input), worktree, ctx.accio / "run" / claim["story"] / REPORT_NAME)
    if tool == "Bash":
        return _verdict(bashpolicy.check(_command(tool_input), _house_elf_judge(worktree, ctx), start_in=worktree))
    return deny(f"{tool} isn't on accio:house-elf's list.")


def _claim_request(command, ctx):
    """The story ID when the command is accio's `accio-claim <ID>` and nothing else; "" for any other command that
    runs a script of that name; None when it runs none."""
    tokens = shellwords.tokens(command)
    words = [token.value for token in tokens if token.kind == "word"]
    if not words or os.path.basename(words[0]) != CLAIM_SCRIPT:
        return None
    is_ours = words[0] == CLAIM_SCRIPT or os.path.realpath(words[0]) == os.path.realpath(ctx.bin_dir / CLAIM_SCRIPT)
    is_alone = len(tokens) == 2 and len(words) == 2
    return words[1] if is_ours and is_alone else ""


def _claim(story_id, current, ctx):
    """A claim to record (curfew writes it under the run lock, replacing an earlier agent's claim on the story)."""
    if not story_id:
        return deny(f"run accio's own `{shlex.quote(str(ctx.bin_dir / CLAIM_SCRIPT))} <ID>` on its own, as the "
                    "brief says.")
    worktree = paths.worktree_root(ctx.root) / story_id
    if not story.STORY_ID.match(story_id) or not worktree.is_dir():
        return deny(f"there is no worktree for {story_id} at {worktree}; claim the story ID from your brief.")
    status = ctx.statuses.get(story_id, "not in this run")
    if status != IN_PROGRESS:
        return deny(f"{story_id} isn't in progress (status: {status}, not {IN_PROGRESS}); claim the story from your "
                    "brief.")
    if current and current["story"] != story_id:
        return deny(f"this agent already claimed {current['story']}.")
    return Decision(True, claim=(story_id, str(worktree)))


def _house_elf_write(target, worktree, report):
    if target and (bashpolicy.in_worktree(target, worktree) or target == pathlib.Path(os.path.realpath(report))):
        return allow()
    return deny(f"house-elf writes only inside {worktree} (never its .git) and its report {report}, not "
                f"{target or 'this file'}.")


def _house_elf_judge(worktree, ctx):
    exact = bashpolicy.command_prefixes(ctx.config.get("agent_allow", []), "agent_allow entry")
    return bashpolicy.Judge(agent="house-elf", prefixes=_check_prefixes(ctx), exact=exact, read_only=True, files=True,
                            git=bashpolicy.HOUSE_ELF_GIT, worktree=worktree, bin_dir=ctx.bin_dir,
                            scripts={"accio-board": frozenset({"refresh"})})


# --- the other agents' Bash ----------------------------------------------------------------------------------------

def _other_judge(agent, kind, ctx):
    if kind == "howler":
        return bashpolicy.Judge(agent=agent, forms=HOWLER_FORMS, bin_dir=ctx.bin_dir)
    if kind != "checks":
        return bashpolicy.Judge(agent=agent, scripts=SCRIPTS[kind], bin_dir=ctx.bin_dir)
    return bashpolicy.Judge(agent=agent, prefixes=_check_prefixes(ctx), read_only=True, git=bashpolicy.READ_ONLY_GIT,
                            scripts=SCRIPTS[kind], bin_dir=ctx.bin_dir, may_cd=True,
                            script_args={"accio-check": PREFECT_CHECK})


def _check_prefixes(ctx):
    return bashpolicy.command_prefixes((check["command"] for check in ctx.config.get("checks", [])), "check")


# --- paths ---------------------------------------------------------------------------------------------------------

def _command(tool_input):
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def _target(tool_input):
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            try:
                return pathlib.Path(os.path.realpath(value))
            except (OSError, ValueError):
                return None
    return None


def _inside(path, folder):
    try:
        return path.is_relative_to(pathlib.Path(os.path.realpath(folder)))
    except (OSError, ValueError):
        return False


def _under(path, accio, pattern):
    """True when `path` is a file under `.accio/` matching `pattern` part by part."""
    real = pathlib.Path(os.path.realpath(accio))
    if not path.is_relative_to(real):
        return False
    parts, wanted = path.relative_to(real).parts, pattern.split("/")
    return len(parts) == len(wanted) and all(fnmatch.fnmatchcase(part, glob) for part, glob in zip(parts, wanted))
