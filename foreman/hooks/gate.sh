#!/bin/bash
# PreToolUse hook (foreman): enforces the "gates" in .claude/foreman.json.
# Each gate says: nothing under <path> may be created or changed until <requires> is committed.
#   "gates": [{"path": "backend/app/engine", "requires": "eval/split.json", "reason": "…"}]
# The check runs against the repo or worktree that holds the target, so it works in agent worktrees.
# File tools are checked exactly. Shell commands are checked best effort, because shell text can hide a path.

INPUT=$(cat)
command -v jq >/dev/null 2>&1 || { echo "BLOCKED: foreman's gate hook needs jq (brew install jq)." >&2; exit 2; }
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
CONFIG="${CLAUDE_PROJECT_DIR:-$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)}/.claude/foreman.json"
[ -f "$CONFIG" ] || exit 0
GATES=$(jq -c '.gates // [] | .[]' "$CONFIG" 2>/dev/null)
[ -n "$GATES" ] || exit 0

existing_dir() { local d="$1"; while [ -n "$d" ] && [ ! -d "$d" ]; do d=$(dirname "$d"); done; echo "${d:-.}"; }

committed() {  # committed <dir inside the repo> <repo-relative file>
  local top
  top=$(git -C "$1" rev-parse --show-toplevel 2>/dev/null) || return 0   # not a git repo: nothing to gate
  git -C "$top" cat-file -e "HEAD:$2" 2>/dev/null
}

block() {
  echo "BLOCKED: $1 Gate: '$2' may only be written after '$3' is committed — $4. (.claude/foreman.json › gates)" >&2
  exit 2
}

while IFS= read -r gate; do
  P=$(echo "$gate" | jq -r '.path' | sed 's#/*$##')
  R=$(echo "$gate" | jq -r '.requires')
  WHY=$(echo "$gate" | jq -r '.reason // "see the backlog"')
  LEAF=$(basename "$P")
  PARENT=$(basename "$(dirname "$P")")
  case "$TOOL" in
    Write|Edit|MultiEdit|NotebookEdit)
      FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
      [[ "$FILE" != /* ]] && FILE="$CWD/$FILE"
      if echo "$FILE" | grep -qF -- "/$P/" || [[ "$FILE" == */"$P" ]]; then
        committed "$(existing_dir "$(dirname "$FILE")")" "$R" || block "'$FILE' is under a gated path." "$P" "$R" "$WHY"
      fi
      ;;
    Bash)
      CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' | awk -f "$(dirname "$0")/lib/strip-heredocs.awk")
      MENTIONS=0
      echo "$CMD" | grep -qF -- "$P" && MENTIONS=1
      # "cd <parent> && mkdir <leaf>" and "mkdir -p <parent>/{a,<leaf>}"
      echo "$CMD" | grep -qF -- "$PARENT" && echo "$CMD" | grep -qE "(^|[/{,[:space:]])$LEAF([/},[:space:];&|]|$)" && MENTIONS=1
      if [ "$MENTIONS" = 1 ]; then
        WRITES=0
        echo "$CMD" | grep -qE '(^|[^A-Za-z0-9_-])(mkdir|touch|cp|mv|tee|install|ln|rsync|unzip|tar|git[[:space:]]+(mv|checkout|restore|apply|am))([^A-Za-z0-9_-]|$)' && WRITES=1
        # In-place edits and scripts that open a file for writing.
        echo "$CMD" | grep -qE '(^|[^A-Za-z0-9_-])(sed|perl)[[:space:]]+(-[A-Za-z]*i|--in-place)' && WRITES=1
        echo "$CMD" | grep -qE "open\\([^)]*['\"](w|a|x)[b+]*['\"]|write_text|write_bytes|\\.mkdir\\(" && WRITES=1
        echo "$CMD" | grep -qE ">+[[:space:]]*[^[:space:]]*$LEAF" && WRITES=1
        [ "$WRITES" = 1 ] && { committed "${CWD:-.}" "$R" || block "the command would create or change files under a gated path." "$P" "$R" "$WHY"; }
      fi
      ;;
  esac
done <<< "$GATES"

exit 0
