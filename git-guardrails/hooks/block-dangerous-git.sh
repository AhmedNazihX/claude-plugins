#!/bin/bash
# PreToolUse hook for Bash: blocks destructive git commands and asks the user before any push.
#
# Each part of the command (split on ; && || | and newlines, heredoc bodies dropped) that runs git is read as
# tokens: git's global options (-C <dir>, -c <k=v>, --git-dir=…, --no-pager …) are skipped, then the subcommand's own
# flags decide. So spacing, flag order and combined short flags (-df, -fu) don't change the verdict.
#
# Blocked (exit 2): force pushes (--force, --force-with-lease, -f, +refspec); reset --hard; clean -f in any form;
# branch -D / --delete --force; checkout -f or a whole-tree pathspec (., :/, *); restore of the whole tree;
# switch --discard-changes / -f; stash drop / clear; worktree remove --force; filter-branch.
# Asks the user: every other push.

HERE="$(cd "$(dirname "$0")" && pwd)"
if ! command -v jq >/dev/null 2>&1; then
  echo "BLOCKED: git-guardrails needs jq to read the command (brew install jq). Until then, shell commands are blocked." >&2
  exit 2
fi

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
[ -n "$COMMAND" ] || exit 0

block() {
  echo "BLOCKED: '$1' — $2. The user has prevented you from doing this." >&2
  exit 2
}

# One git invocation per line: drop heredoc bodies, split on command separators.
PARTS=$(printf '%s\n' "$COMMAND" | awk -f "$HERE/lib/strip-heredocs.awk" | sed -E 's/(\&\&|\|\||;|\||\(|\)|`)/\n/g')

ASK=""
while IFS= read -r part; do
  # Tokens; quotes are dropped so "git" 'push' still reads as git push.
  read -ra T <<<"$(printf '%s' "$part" | tr -d "\"'")"
  n=${#T[@]}
  i=0
  # Find the git executable (after env assignments, `command`, `sudo`, `env` …).
  while [ $i -lt $n ] && [[ ! "${T[$i]}" =~ (^|/)git$ ]]; do i=$((i + 1)); done
  [ $i -lt $n ] || continue
  i=$((i + 1))
  # Skip git's global options.
  while [ $i -lt $n ]; do
    case "${T[$i]}" in
      -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--super-prefix|--config-env) i=$((i + 2)) ;;
      -*) i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  [ $i -lt $n ] || continue
  SUB=${T[$i]}
  ARGS=("${T[@]:$((i + 1))}")
  has() {  # has <regex>: some argument matches
    local a
    for a in "${ARGS[@]}"; do [[ "$a" =~ $1 ]] && return 0; done
    return 1
  }
  short() {  # short <letter>: a combined short-flag argument contains the letter (-fd, -df, -xdf)
    has "^-[A-Za-z]*$1[A-Za-z]*$"
  }
  WHOLE_TREE='^(\.|:/|\*|\./)$'
  case "$SUB" in
    push)
      if has '^--force' || short f || has '^\+'; then block "$part" "force push"; fi
      ASK="$COMMAND" ;;
    reset)
      has '^--hard$' && block "$part" "reset --hard discards work" ;;
    clean)
      if short f || has '^--force$'; then block "$part" "clean -f deletes untracked files"; fi ;;
    branch)
      if short D; then block "$part" "branch -D deletes an unmerged branch"; fi
      if { has '^--delete$' || short d; } && { has '^--force$' || short f; }; then block "$part" "forced branch delete"; fi ;;
    checkout)
      if has '^--force$' || short f; then block "$part" "checkout -f discards changes"; fi
      has "$WHOLE_TREE" && block "$part" "checkout of the whole tree discards changes" ;;
    restore)
      has "$WHOLE_TREE" && block "$part" "restore of the whole tree discards changes" ;;
    switch)
      if has '^--discard-changes$' || has '^--force$' || short f; then block "$part" "switch discarding changes"; fi ;;
    stash)
      [[ "${ARGS[0]}" =~ ^(drop|clear)$ ]] && block "$part" "stash ${ARGS[0]} deletes stashed work" ;;
    worktree)
      if [ "${ARGS[0]}" = remove ] && { has '^--force$' || short f; }; then block "$part" "worktree remove --force deletes uncommitted work"; fi ;;
    filter-branch)
      block "$part" "filter-branch rewrites history" ;;
  esac
done <<<"$PARTS"

if [ -n "$ASK" ]; then
  jq -n --arg cmd "$ASK" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: ("git push needs your approval: " + $cmd)
    }
  }'
fi
exit 0
