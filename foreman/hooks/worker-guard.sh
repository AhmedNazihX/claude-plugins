#!/bin/bash
# PreToolUse hook (foreman): keeps a story worker inside its job. It applies to subagents only (the hook input
# carries `agent_id`; the main thread, where the orchestrator runs, has none, so a shell left inside a worktree after
# `cd <worktree> && uv run pytest` can still merge). For a subagent it applies when the command runs in an agent
# worktree (a path under .claude/worktrees/) or on a story branch (story/<ID>-<slug>), so a detached checkout can't
# switch it off. There it blocks what only the orchestrator may do:
#   - push, rebase, pull (except `git pull <remote> <base>`), merging anything but the base branch (`git merge
#     <base>` stays allowed: story-finish asks for it to resolve conflicts), moving to another branch or commit,
#     creating branches (switch/checkout -b/-c/--track/--orphan, stuck forms included, and `worktree add` without
#     --detach), fetching into a branch (a refspec with a destination), `branch -f/-c/-M`, `branch -m` except
#     renaming this branch to a story name, `update-ref`, `symbolic-ref` writes, `send-pack` and `http-push`. One
#     move is allowed: the bare `git switch story/<ID>-<slug>` from a branch that isn't a story branch, so a
#     relaunched worker can continue a story (story-start › Continue);
#   - editing docs/BACKLOG.md (file tools, shell writes, or backlog.py tick / note / set-deps / add without a plain
#     --dry-run flag);
#   - aliases: `git -c alias.…`, `git config` writes to alias.* or include*, and any git subcommand git doesn't
#     list (an alias can hide a push).
# `git -C <dir>` on a separate clone is checked for push only: the clone's origin can be the shared repo or its
# remote, while its other refs are its own. On another worktree of the same repo every check applies, since
# worktrees share refs; there only detaching that worktree's own HEAD is allowed. A `-C` path the guard can't
# resolve (quoted, or relative after a `cd`) is checked as this worktree, with every check, and so is any part where
# the repo is named another way too (--git-dir, --work-tree, a second -C, or GIT_DIR= and the like).
# Text inside quotes (commit messages, echo) is ignored. The base branch comes from .claude/foreman.json
# (`base_branch`, default main). Shell checks are best effort.

command -v jq >/dev/null 2>&1 || { echo "BLOCKED: foreman's worker guard needs jq (brew install jq)." >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
INPUT=$(cat)
[ -n "$(echo "$INPUT" | jq -r '.agent_id // empty')" ] || exit 0   # the main thread is the orchestrator
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
TOP=$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null) || exit 0
BRANCH=$(git -C "${CWD:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null)
case "$TOP" in
  */.claude/worktrees/*) ;;
  *) [[ "$BRANCH" =~ ^story/[A-Z]{1,3}[0-9]+[a-z]?- ]] || exit 0 ;;
esac
common_dir() { (cd "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P); }
COMMON=$(common_dir "$TOP")   # the repository every worktree of it shares: refs, branches, remotes
MAIN=$(dirname "$COMMON")
CONFIG="${CLAUDE_PROJECT_DIR:-$MAIN}/.claude/foreman.json"
BASE=$(jq -r '.base_branch // "main"' "$CONFIG" 2>/dev/null)
BASE=${BASE:-main}

# The way through, named at the end of each message.
ALT_BACKLOG="Put it under Follow-ups in your report; the orchestrator updates the backlog."
ALT_REPORT="Report it in your final message; the orchestrator does it."
ALT_READ="To read old code, use 'git show <commit>:<path>', 'git log -p' or 'git diff <commit>'."
ALT_RESTORE="To restore a file, run 'git checkout -- <path>'. $ALT_READ"
ALT_SCRATCH="For a scratch copy, run 'git worktree add --detach <path> <commit>'."
ALT_FETCH="Fetch without a destination ('git fetch <remote> <branch>') and read FETCH_HEAD; the orchestrator moves branches."
ALT_ALIAS="Run the git command itself, unquoted."
block() {  # block <what was blocked> <the allowed alternative>
  echo "BLOCKED: $1 Story workers commit on their own branch ('$BRANCH') and report; the orchestrator merges," \
       "pushes and edits the backlog. $2" >&2
  exit 2
}
is_backlog() { [[ "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" =~ (^|/)docs/backlog\.md$ ]]; }

# Option tests on REST (the arguments after the subcommand).
has_opt() { [[ " ${REST[*]} " =~ \ $1\  ]]; }
has_prefix() { local a; for a in "${REST[@]}"; do [[ "$a" == "$1"* ]] && return 0; done; return 1; }
has_short() {  # has_short <letters>: a short option among them, alone, bundled (-qb) or stuck (-bname)
  local a; for a in "${REST[@]}"; do [[ "$a" =~ ^-[a-zA-Z]*[$1] ]] && return 0; done; return 1
}
# The words before `git` in a command part: nothing, VAR=value, or a wrapper that runs its arguments as a command.
# A number (timeout 60) or the word after a short option (nice -n 10, timeout -s KILL) is a wrapper's value.
is_command_position() {
  local t prev=""
  for t in "$@"; do
    case "$t" in
      *=* | -* | _q_ | [0-9]* | env | command | exec | time | timeout | nice | nohup | stdbuf | sudo | xargs | \
      if | then | do | else | while | until | '!' | '{') ;;
      *) [[ "$prev" =~ ^-[a-zA-Z]$ ]] || return 1 ;;
    esac
    prev=$t
  done
}
KNOWN=""
is_known_sub() {  # git's own commands and git-* programs on PATH; never aliases
  [ -n "$KNOWN" ] || KNOWN=$(git --list-cmds=main,others 2>/dev/null)
  printf '%s\n' "$KNOWN" | grep -qxF -- "$1"
}

check_alias() {  # check_alias <name=value of a `git -c` or `--config-env`>
  [[ "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" == alias.* ]] &&
    block "git -c alias.… (an alias can hide any git command)." "$ALT_ALIAS"
  return 0
}

is_dry_run() {  # is_dry_run <backlog.py call>: --dry-run as a flag, before any `--`, with no comment or redirection
  local w words
  [[ "$1" == *[\#\<\>]* ]] && return 1
  read -ra words <<<"$1"
  for w in "${words[@]}"; do
    [ "$w" = -- ] && return 1
    [ "$w" = --dry-run ] && return 0
  done
  return 1
}

check_backlog_py() {  # backlog.py's writing commands, unless the same call is a dry run
  local seg writes='[[:space:]](tick|note|set-deps|add)([[:space:]]|$)'
  while IFS= read -r seg; do
    [[ "$seg" =~ $writes ]] || continue
    is_dry_run "$seg" && continue
    block "changing the backlog with backlog.py." "$ALT_BACKLOG"
  done <<<"$(printf '%s\n' "$1" | grep -oE 'backlog\.py[^;&|]*')"
}

check_switch() {  # switch|checkout, with SUB, REST, TARGETS, GDIR and SCRATCH set
  local t
  if has_short bBcCt || has_prefix --create || has_prefix --force-create || has_prefix --orphan || has_prefix --track; then
    block "git $SUB with a new branch (a worker stays on its story branch)." "$ALT_REPORT"
  fi
  if has_opt --detach || { [ "$SUB" = switch ] && has_short d; }; then
    [ -n "$SCRATCH" ] && return                                # a scratch worktree detaches its own HEAD
    block "git $SUB --detach (a worker stays on its story branch)." "$ALT_READ"
  fi
  has_opt -- && return                                         # checkout <tree-ish> -- <paths>
  [ "${#TARGETS[@]}" -ge 1 ] || return
  t=${TARGETS[0]}
  [ "$t" = _q_ ] && block "git $SUB with a quoted argument (the guard can't check it)." "$ALT_RESTORE"
  case "$t" in -* | *@\{-*) block "git $SUB $t (the previous branch; a worker stays on its story branch)." "$ALT_READ" ;; esac
  # A commit or branch first: a name can be both a branch and a file, and without `--` git takes the branch.
  if git -C "$TOP" rev-parse --verify --quiet "$t^{commit}" >/dev/null; then
    # A scratch worktree may check out a commit (detached), never a branch: its commits would move that branch.
    [ -n "$SCRATCH" ] && ! git -C "$TOP" show-ref --verify --quiet "refs/heads/$t" && return
    # Continue a story: a fresh worktree (not yet on a story branch) switches onto an existing story branch,
    # in its own checkout (no `git -C`) and once per command ($BRANCH is read once, before any switch).
    if [ "$SUB" = switch ] && [ -z "$GDIR" ] && [ -z "$SWITCHED" ] &&
      [[ "$t" =~ ^story/[A-Z]{1,3}[0-9]+[a-z]?- ]] && [[ ! "$BRANCH" =~ ^story/ ]] &&
      git -C "$TOP" show-ref --verify --quiet "refs/heads/$t"; then
      SWITCHED=1
      return
    fi
    block "git $SUB $t (a worker stays on its story branch)." "$ALT_READ"
  fi
  if [ "$SUB" = checkout ]; then                               # a path: restoring files is fine
    { [ -e "$TOP/$t" ] || [ -e "${CWD:-$TOP}/$t" ]; } && return
    git -C "${CWD:-$TOP}" ls-files --error-unmatch -- "$t" >/dev/null 2>&1 && return
  fi
  # Neither a file nor a commit: git would guess a branch from a remote one (`origin/<t>`) and create it.
  block "git $SUB $t (not a file or a commit here; git may create a branch from a remote one)." "$ALT_RESTORE"
}

check_branch() {  # no forcing, copying or force-renaming; -m only renames this branch to a story branch
  local alt="Rename your own branch with 'git branch -m story/<ID>-<slug>'."
  if has_short f || has_prefix --force; then block "git branch -f." "$ALT_REPORT"; fi
  if has_short cC || has_prefix --copy; then block "git branch -c (a copy makes a branch)." "$ALT_REPORT"; fi
  if has_short M; then block "git branch -M (it can overwrite another branch)." "$alt"; fi
  has_short m || has_prefix --move || return 0
  # Only in this checkout: `git -C <other checkout> branch -m` would rename that checkout's branch.
  # ($rdir and $override are check_git_part's, the caller.)
  if [ -n "$GDIR" ]; then
    { [ -n "$rdir" ] && [ -z "$override" ] && [ "$(git -C "$rdir" rev-parse --show-toplevel 2>/dev/null)" = "$TOP" ]; } ||
      block "git -C $GDIR branch -m (it renames another checkout's branch)." "$alt"
  fi
  [ "${#TARGETS[@]}" = 1 ] && [[ "${TARGETS[0]}" =~ ^story/[A-Z]{1,3}[0-9]+[a-z]?-[^[:space:]]+$ ]] && return 0
  block "git branch -m ${TARGETS[*]} (only renaming your own branch to its story name is allowed)." "$alt"
}

check_config() {  # writing an alias, or an include that could bring one in
  local t n=${#TARGETS[@]}
  case "${TARGETS[0]}" in get | list) return 0 ;; esac
  has_prefix --get && return 0
  case "${TARGETS[0]}" in set | unset) n=$((n - 1)) ;; esac
  [ "$n" -ge 2 ] || [ "${TARGETS[0]}" = set ] || has_prefix --add || has_prefix --replace-all || return 0
  local key=${TARGETS[0]}
  case "$key" in set | unset) key=${TARGETS[1]} ;; esac
  [ "$key" = _q_ ] && block "git config with a quoted key (it could be an alias)." "$ALT_ALIAS"  # a value may be quoted
  for t in "${TARGETS[@]}"; do
    case "$(printf '%s' "$t" | tr '[:upper:]' '[:lower:]')" in
      alias.* | include.* | includeif.*) block "git config $t (an alias can hide any git command)." "$ALT_ALIAS" ;;
    esac
  done
  return 0
}

check_worktree() {  # `git worktree add` only for a detached scratch copy
  [ "${REST[0]}" = add ] || return
  if has_short bB || has_prefix --orphan; then block "git worktree add with a new branch." "$ALT_SCRATCH"; fi
  has_opt --detach || has_short d || block "git worktree add without --detach (it checks out a branch or makes one)." "$ALT_SCRATCH"
}

check_fetch() {  # a refspec with a destination (src:dst) writes a branch into the shared repo
  local t
  for t in "${TARGETS[@]:1}"; do
    [[ "$t" == *:* || "$t" == _q_ ]] && block "git fetch $t (a refspec with a destination writes a branch)." "$ALT_FETCH"
  done
}

# One command part: finds `git`, reads its global options and checks the subcommand.
check_git_part() {
  local -a T
  read -ra T <<<"$1"
  [ ${#T[@]} -gt 0 ] || return
  case "${T[0]}" in cd | pushd) CDED=1 ;; esac
  local i=0 at_cmd=""
  while [ $i -lt ${#T[@]} ] && [[ ! "${T[$i]}" =~ (^|/)git$ ]]; do i=$((i + 1)); done
  [ $i -lt ${#T[@]} ] || return
  is_command_position "${T[@]:0:$i}" && at_cmd=1
  i=$((i + 1))
  GDIR=""
  local override=$REDIRECTED                                 # the repo is named some other way than one -C
  while [ $i -lt ${#T[@]} ]; do
    case "${T[$i]}" in
      -C) [ -n "$GDIR" ] && override=1; GDIR=${T[$((i + 1))]//_s_/ }; i=$((i + 2)) ;;
      -c | --config-env) check_alias "${T[$((i + 1))]}"; i=$((i + 2)) ;;
      --config-env=*) check_alias "${T[$i]#--config-env=}"; i=$((i + 1)) ;;
      --git-dir | --work-tree) override=1; i=$((i + 2)) ;;
      --git-dir=* | --work-tree=*) override=1; i=$((i + 1)) ;;
      --namespace | --super-prefix) i=$((i + 2)) ;;
      -*) i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  # `git -C <dir>` acts on <dir>'s repo. A separate clone is exempt from every check but push.
  # A scratch worktree of this repo (outside the agent worktrees, not on a story branch, not the main checkout)
  # shares its refs, so every check still applies; only moving that copy's own HEAD to a detached commit is
  # allowed there (the test auditor does this). A path the guard can't resolve is checked as this worktree.
  SCRATCH=""
  local clone="" rdir="" gtop gbr
  if [ -n "$GDIR" ]; then
    if [[ "$GDIR" == /* ]]; then rdir=$GDIR
    elif [ -z "$CDED" ]; then rdir="${CWD:-$TOP}/$GDIR"      # after a `cd`, a relative path is unknown here
    fi
  fi
  if [ -n "$rdir" ] && [ -z "$override" ]; then
    gtop=$(git -C "$rdir" rev-parse --show-toplevel 2>/dev/null)
    gbr=$(git -C "$rdir" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ -n "$gtop" ] && [[ "$gtop" != */.claude/worktrees/* ]] && [[ ! "$gbr" =~ ^story/ ]] && [ "$gtop" != "$MAIN" ]; then
      if [ "$(common_dir "$rdir")" = "$COMMON" ]; then SCRATCH=1; else clone=1; fi
    fi
  fi
  SUB=${T[$i]}
  [ -n "$at_cmd" ] && [ -n "$SUB" ] && ! is_known_sub "$SUB" &&
    block "git $SUB (not a git command this guard knows; an alias can hide a push or a merge)." "$ALT_ALIAS"
  # A clone's own refs are its own, but its push can reach the shared repo (its origin) or the shared remote.
  [ -n "$clone" ] && [ "$SUB" != push ] && return
  REST=("${T[@]:$((i + 1))}")
  collect_targets
  check_sub
}

collect_targets() {  # TARGETS: the positional arguments in REST; for merge and pull, option values are skipped
  TARGETS=()
  local a skip=0
  for a in "${REST[@]}"; do
    if [ $skip = 1 ]; then skip=0; continue; fi
    if [ $skip = 2 ]; then skip=0; [ "$a" = _q_ ] && continue; fi  # the quoted value of `--opt="x y"`
    case "$SUB:$a" in
      merge:-m | merge:-X | merge:-s | merge:-F | merge:--strategy | merge:--strategy-option | merge:--file | \
      merge:--message | merge:--into-name | pull:-X | pull:-s | pull:--strategy | pull:--strategy-option) skip=1 ;;
      *:-*=) skip=2 ;;                                      # --message="x y" reads as `--message= _q_`
      *:-?* | *:--) ;;
      *) TARGETS+=("${a//_s_/ }") ;;
    esac
  done
}

check_sub() {  # the subcommand's own checks, with SUB, REST and TARGETS set
  local a
  case "$SUB" in
    push) block "git push." "$ALT_REPORT" ;;
    rebase) block "git rebase (story branches are merged, never rebased)." "$ALT_REPORT" ;;
    update-ref | send-pack | http-push) block "git $SUB." "$ALT_REPORT" ;;
    symbolic-ref)
      if [ "${#TARGETS[@]}" -ge 2 ] || has_short d || has_prefix --delete; then
        block "git symbolic-ref with a write." "$ALT_REPORT"
      fi ;;
    config) check_config ;;
    pull)
      if has_prefix --rebase || has_short r || [ "${#TARGETS[@]}" -ne 2 ] || [ "${TARGETS[1]}" != "$BASE" ]; then
        block "git pull." "To take the base branch in, run 'git merge $BASE'."
      fi ;;
    merge)
      { has_opt --abort || has_opt --continue || has_opt --quit; } && return
      for a in "${TARGETS[@]}"; do
        [ "$a" = "$BASE" ] || [ "$a" = "origin/$BASE" ] || block "git merge $a (only 'git merge $BASE' is allowed, to resolve conflicts)." "$ALT_REPORT"
      done ;;
    branch) check_branch ;;
    fetch) check_fetch ;;
    worktree) check_worktree ;;
    switch | checkout) check_switch ;;
  esac
}

case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
    is_backlog "$FILE" && block "editing docs/BACKLOG.md." "$ALT_BACKLOG"
    ;;
  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty' | awk -f "$HERE/lib/strip-heredocs.awk")
    # Quoted text is content (commit messages, echo), not commands. A backslash-escaped space stays in its word.
    CMD=$(printf '%s\n' "$RAW" | sed -E "s/\"[^\"]*\"/ _q_ /g; s/'[^']*'/ _q_ /g; s/\\\\ /_s_/g")
    LOWER=$(printf '%s' "$CMD" | tr '[:upper:]' '[:lower:]')
    check_backlog_py "$CMD"
    if echo "$LOWER" | grep -qE '(>+|(^|[[:space:];&|])tee([[:space:]]+-a)?|(^|[[:space:];&|])(sed|perl)[[:space:]]+(-[a-z]*i|--in-place))[^;&|]*docs/backlog\.md'; then
      block "writing docs/BACKLOG.md." "$ALT_BACKLOG"
    fi
    SWITCHED=""
    CDED=""
    REDIRECTED=""   # GIT_DIR and the like point git at a repo other than the -C path
    [[ "$CMD" =~ (^|[^A-Za-z0-9_])GIT_(DIR|WORK_TREE|COMMON_DIR)= ]] && REDIRECTED=1
    # Parts: split on && || ; | ( ) ` and a lone & (not the & of 2>&1 or &>).
    while IFS= read -r part; do
      check_git_part "$part"
    done <<<"$(printf '%s\n' "$CMD" | sed -E 's/(\&\&|\|\||;|\||\(|\)|`)/\n/g; s/>&/_GA_/g; s/&>/_AG_/g; s/&/\n/g; s/_GA_/>\&/g; s/_AG_/\&>/g')"
    ;;
esac
exit 0
