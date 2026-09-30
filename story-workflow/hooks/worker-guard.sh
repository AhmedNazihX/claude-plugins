#!/bin/bash
# PreToolUse hook (story-workflow): keeps a story worker inside its job. It applies to subagents only (the hook input
# carries `agent_id`; the main thread, where the orchestrator runs, has none, so a shell left inside a worktree after
# `cd <worktree> && uv run pytest` can still merge). For a subagent it applies when the command runs in an agent
# worktree (a path under .claude/worktrees/) or on a story branch (story/<ID>-<slug>), so a detached checkout can't
# switch it off. There it blocks what only the orchestrator may do:
#   - push, rebase, pull (except `git pull <remote> <base>`), merging anything but the base branch (`git merge
#     <base>` stays allowed: story-finish asks for it to resolve conflicts), moving to another branch or commit,
#     creating branches, `branch -f` and `update-ref`;
#   - editing docs/BACKLOG.md (file tools, shell writes, or backlog.py tick / note / set-deps / add).
# Text inside quotes (commit messages, echo) is ignored. The base branch comes from .claude/story-workflow.json
# (`base_branch`, default main). Shell checks are best effort.

command -v jq >/dev/null 2>&1 || { echo "BLOCKED: story-workflow's worker guard needs jq (brew install jq)." >&2; exit 2; }
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
MAIN=$(cd "$(dirname "$(git -C "$TOP" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")" && pwd)
CONFIG="${CLAUDE_PROJECT_DIR:-$MAIN}/.claude/story-workflow.json"
BASE=$(jq -r '.base_branch // "main"' "$CONFIG" 2>/dev/null)
BASE=${BASE:-main}

block() {
  echo "BLOCKED: $1 Story workers commit on their own branch ('$BRANCH') and report; the orchestrator merges, pushes and edits the backlog. Put it in your report instead." >&2
  exit 2
}
is_backlog() { [[ "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" =~ (^|/)docs/backlog\.md$ ]]; }

case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
    is_backlog "$FILE" && block "editing docs/BACKLOG.md."
    ;;
  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty' | awk -f "$HERE/lib/strip-heredocs.awk")
    # Quoted text is content (commit messages, echo), not commands.
    CMD=$(printf '%s\n' "$RAW" | sed -E "s/\"[^\"]*\"/ _q_ /g; s/'[^']*'/ _q_ /g")
    LOWER=$(printf '%s' "$CMD" | tr '[:upper:]' '[:lower:]')
    echo "$CMD" | grep -qE 'backlog\.py[^;&|]*[[:space:]](tick|note|set-deps|add)([[:space:]]|$)' && block "changing the backlog with backlog.py."
    if echo "$LOWER" | grep -qE '(>+|(^|[[:space:];&|])tee([[:space:]]+-a)?|(^|[[:space:];&|])(sed|perl)[[:space:]]+(-[a-z]*i|--in-place))[^;&|]*docs/backlog\.md'; then
      block "writing docs/BACKLOG.md."
    fi
    while IFS= read -r part; do
      read -ra T <<<"$part"
      i=0
      while [ $i -lt ${#T[@]} ] && [[ ! "${T[$i]}" =~ (^|/)git$ ]]; do i=$((i + 1)); done
      [ $i -lt ${#T[@]} ] || continue
      i=$((i + 1))
      GDIR=""
      while [ $i -lt ${#T[@]} ]; do
        case "${T[$i]}" in
          -C) GDIR=${T[$((i + 1))]}; i=$((i + 2)) ;;
          -c|--git-dir|--work-tree) i=$((i + 2)) ;;
          -*) i=$((i + 1)) ;;
          *) break ;;
        esac
      done
      # `git -C <dir>` acts on <dir>'s repo: a scratch copy outside the agent worktrees isn't the story's checkout.
      if [ -n "$GDIR" ]; then
        [[ "$GDIR" == /* ]] || GDIR="${CWD:-$TOP}/$GDIR"
        GTOP=$(git -C "$GDIR" rev-parse --show-toplevel 2>/dev/null)
        GBR=$(git -C "$GDIR" rev-parse --abbrev-ref HEAD 2>/dev/null)
        if [ -n "$GTOP" ] && [[ "$GTOP" != */.claude/worktrees/* ]] && [[ ! "$GBR" =~ ^story/ ]] && [ "$GTOP" != "$MAIN" ]; then
          continue
        fi
      fi
      SUB=${T[$i]}
      REST=("${T[@]:$((i + 1))}")
      # Positional arguments, skipping the values of options that take one.
      TARGETS=()
      skip=0
      for a in "${REST[@]}"; do
        if [ $skip = 1 ]; then skip=0; continue; fi
        case "$a" in
          -m|-X|-s|-F|--strategy|--strategy-option|--file|--message|--into-name) skip=1 ;;
          -*|_q_) ;;
          *) TARGETS+=("$a") ;;
        esac
      done
      has_opt() { [[ " ${REST[*]} " =~ \ $1\  ]]; }
      case "$SUB" in
        push) block "git push." ;;
        rebase) block "git rebase (story branches are merged, never rebased)." ;;
        update-ref) block "git update-ref." ;;
        pull)
          if has_opt --rebase || has_opt -r || [ "${#TARGETS[@]}" -lt 2 ] || [ "${TARGETS[1]}" != "$BASE" ]; then
            block "git pull (use 'git merge $BASE' to take the base branch in)."
          fi ;;
        merge)
          { has_opt --abort || has_opt --continue || has_opt --quit; } && continue
          for t in "${TARGETS[@]}"; do
            [ "$t" = "$BASE" ] || [ "$t" = "origin/$BASE" ] || block "git merge $t (only 'git merge $BASE' is allowed, to resolve conflicts)."
          done ;;
        branch)
          if has_opt -f || has_opt --force; then block "git branch -f."; fi ;;
        switch|checkout)
          for o in -b -B -c -C --create --force-create --orphan --detach; do
            has_opt "$o" && block "git $SUB $o (a worker stays on its story branch)."
          done
          has_opt -- && continue                                   # checkout <tree-ish> -- <paths>
          [ "${#TARGETS[@]}" -ge 1 ] || continue
          t=${TARGETS[0]}
          [ -e "$TOP/$t" ] || [ -e "${CWD:-$TOP}/$t" ] && continue # a path: restoring files is fine
          if git -C "$TOP" rev-parse --verify --quiet "$t^{commit}" >/dev/null; then
            block "git $SUB $t (a worker stays on its story branch; check old commits in a scratch worktree)."
          fi ;;
      esac
    done <<<"$(printf '%s\n' "$CMD" | sed -E 's/(\&\&|\|\||;|\||\(|\)|`)/\n/g')"
    ;;
esac
exit 0
