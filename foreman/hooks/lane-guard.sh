#!/bin/bash
# PreToolUse hook (foreman): on story branches (story/<ID>-<slug>), blocks access to the folders a
# story's lane must never see, as configured in .claude/foreman.json:
#   "lanes":   {"Corpus": {"deny": ["eval"], "allow": []}}
#   "stories": {"C2": {"deny": ["eval"], "allow": ["eval/split.json"]}}      (a story entry overrides its lane)
# deny and allow are repo-relative paths. The story's lane comes from `backlog.py info <ID>`.
# The branch is read from the hook's cwd, which is the worktree root for worktree agents.
# Paths are checked against every checkout of the repo (this worktree, the main checkout, other story worktrees
# and scratch worktrees), since only this worktree is sparse. File tools are checked exactly; shell commands are
# best effort: the sparse checkout the worker sets up (and a reviewer agent, if configured) are the backstops.

set -f   # deny/allow entries are paths, never globs
INPUT=$(cat)
HOOKS="$(cd "$(dirname "$0")" && pwd)"
BACKLOG_PY="${CLAUDE_PLUGIN_ROOT:-$HOOKS/..}/scripts/backlog.py"
command -v jq >/dev/null 2>&1 || { echo "BLOCKED: foreman's lane guard needs jq (brew install jq)." >&2; exit 2; }

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
CONFIG="${CLAUDE_PROJECT_DIR:-$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)}/.claude/foreman.json"
[ -f "$CONFIG" ] || exit 0
BRANCH=$(git -C "${CWD:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
ID=$(echo "$BRANCH" | sed -nE 's#^story/([A-Z]{1,3}[0-9]+[a-z]?)-.*#\1#p')
[ -n "$ID" ] || exit 0

RULE=$(jq -c --arg id "$ID" '.stories[$id] // empty' "$CONFIG")
if [ -z "$RULE" ]; then
  command -v python3 >/dev/null 2>&1 || { echo "BLOCKED: foreman's lane guard needs python3 to find story $ID's lane." >&2; exit 2; }
  ROOT_FOR_BACKLOG=$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)
  LANE=$(cd "$ROOT_FOR_BACKLOG" 2>/dev/null && python3 "$BACKLOG_PY" info "$ID" 2>/dev/null | jq -r '.lane // empty')
  [ -n "$LANE" ] && RULE=$(jq -c --arg l "$LANE" '.lanes[$l] // empty' "$CONFIG")
fi
[ -n "$RULE" ] || exit 0
DENY=$(echo "$RULE" | jq -r '.deny // [] | .[]' | sed 's#^/*##; s#/*$##')
ALLOW=$(echo "$RULE" | jq -r '.allow // [] | .[]' | sed 's#^/*##; s#/*$##')
[ -n "$DENY" ] || exit 0

ROOT=$(cd "$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)" && pwd -P)
MAIN=$(cd "$(dirname "$(git -C "${CWD:-.}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")" && pwd -P)
# Every checkout of this repo; only ROOT (this worktree) is sparse.
OTHERS=$(git -C "${CWD:-.}" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | while IFS= read -r w; do
  (cd "$w" 2>/dev/null && pwd -P); done | grep -vxF "$ROOT")
BASES=$(printf '%s\n%s\n%s\n' "$ROOT" "$MAIN" "$OTHERS" | awk 'NF && !seen[$0]++')

block() {
  echo "BLOCKED: $1 Branch '$BRANCH' (story $ID) must not access: $(echo $DENY | tr ' ' ',') (.claude/foreman.json). If you believe you need this, stop and ask the user." >&2
  exit 2
}

# Physical path (symlinks such as macOS /var → /private/var resolved), for paths that may not exist yet.
physical() {
  local d="$1" rest=""
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do rest="/$(basename "$d")$rest"; d=$(dirname "$d"); done
  echo "$(cd "$d" 2>/dev/null && pwd -P)$rest"
}

# Repo-relative form of a path from a file tool (absolute paths in any checkout of this repo). The root of a
# checkout other than this worktree comes back as "@other-root": searching it would reach its denied folders.
relpath() {
  local p="$1" base
  [[ "$p" != /* ]] && p="$ROOT/$p"
  p=$(physical "$p")
  [ "$p" = "$ROOT" ] && { echo "."; return; }
  while IFS= read -r base; do
    [ -n "$base" ] || continue
    [ "$p" = "$base" ] && { echo "@other-root"; return; }
    [[ "$p" == "$base"/* ]] && { echo "${p#"$base"/}"; return; }
  done <<<"$BASES"
  echo "$p"
}

replace_literal() {  # replace_literal <text> <from> <to>: every occurrence, no regex or glob meaning
  printf '%s' "$1" | F="$2" T="$3" awk 'BEGIN { f = ENVIRON["F"]; t = ENVIRON["T"] }
    { out = ""; line = $0
      while ((i = index(line, f)) > 0) { out = out substr(line, 1, i - 1) t; line = substr(line, i + length(f)) }
      print out line }'
}

denied_rel() {  # denied_rel <repo-relative path>
  local rel="$1" d a IFS=$'\n'
  [ "$rel" = "@other-root" ] && return 0
  for a in $ALLOW; do [[ "$rel" == "$a" || "$rel" == "$a"/* ]] && return 1; done
  for d in $DENY; do [[ "$rel" == "$d" || "$rel" == "$d"/* ]] && return 0; done
  return 1
}

denied_glob() {  # a glob or search path mentioning a denied folder as a path segment
  local g="$1" d IFS=$'\n'
  for d in $DENY; do
    echo "$g" | grep -qE "(^|/|\*\*/)$d(/|$)" && ! denied_allowed_only "$g" && return 0
  done
  return 1
}
denied_allowed_only() { local a IFS=$'\n'; for a in $ALLOW; do [[ "$1" == *"$a"* ]] && return 0; done; return 1; }

# A bare word equal to a denied folder counts as a path unless it is a command name (`eval "$(…)"`) or an
# option's value (`pytest -k eval`).
bare_denied_word() {  # bare_denied_word <command text> <folder>
  local part w prev i j IFS=$' \t\n'
  while IFS= read -r part; do
    read -ra W <<<"$(printf '%s' "$part" | tr -d "\"'")"
    i=0
    while [ $i -lt ${#W[@]} ] && [[ "${W[$i]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do i=$((i + 1)); done
    prev=""
    for ((j = i + 1; j < ${#W[@]}; j++)); do
      w=${W[$j]}; prev=${W[$((j - 1))]}
      [ "$w" = "$2" ] || [ "$w" = "./$2" ] || continue
      [[ "$prev" =~ ^-[A-Za-z]$ || "$prev" =~ ^--[A-Za-z][A-Za-z-]*$ ]] && continue
      return 0
    done
  done <<<"$(printf '%s\n' "$1" | sed -E 's/(\&\&|\|\||;|\||\$\(|\(|\)|`)/\n/g')"
  return 1
}

case "$TOOL" in
  Read|Write|Edit|MultiEdit|NotebookEdit)
    P=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
    [ -n "$P" ] && denied_rel "$(relpath "$P")" && block "'$P' is in a denied folder."
    ;;
  Grep|Glob)
    SP=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
    [ -n "$SP" ] && denied_rel "$(relpath "$SP")" && block "searching '$SP' is denied."
    for G in "$(echo "$INPUT" | jq -r '.tool_input.glob // empty')" \
             "$( [ "$TOOL" = Glob ] && echo "$INPUT" | jq -r '.tool_input.pattern // empty')"; do
      [ -n "$G" ] && denied_glob "$G" && block "the pattern '$G' reaches a denied folder."
    done
    ;;
  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    if echo "$RAW" | grep -qE 'sparse-checkout' && ! echo "$RAW" | grep -qE 'sparse-checkout[[:space:]]+list([[:space:];&|]|$)'; then
      block "changing the sparse checkout could bring denied folders back."
    fi
    CMD=$(echo "$RAW" | awk -f "$HOOKS/lib/strip-heredocs.awk" \
          | sed -E "s/(-m|--message)(=|[[:space:]]+)\"[^\"]*\"//g; s/(-m|--message)(=|[[:space:]]+)'[^']*'//g")
    # Absolute paths into this worktree or the main checkout become relative (a leading space keeps the boundary).
    # Literal replace in awk: bash 3.2 (macOS) mangles quotes in ${CMD//"$x"/…}, and a hook that crashes
    # lets the call through.
    while IFS= read -r base; do
      [ -n "$base" ] || continue
      for form in "$base" "${base#/private}"; do  # macOS: /var and /tmp are /private/…
        # The root of another checkout, as a whole word, reaches its denied folders (`grep -rn x <main>`).
        if [ "$base" != "$ROOT" ] && printf '%s' "$CMD" | F="$form" awk 'BEGIN { f = ENVIRON["F"] }
          { s = $0; while ((i = index(s, f)) > 0) { c = substr(s, i + length(f), 1)
              if (c == "" || c ~ /[[:space:];&|"\047)]/) found = 1; s = substr(s, i + length(f)) } }
          END { exit !found }'; then
          block "the command reaches another checkout of the repo ('$form'), which isn't sparse. Work inside your own worktree."
        fi
        CMD=$(replace_literal "$CMD" "$form/" " ")
      done
    done <<<"$BASES"
    IFS=$'\n'
    for a in $ALLOW; do CMD=$(echo "$CMD" | sed -E "s#(^|[[:space:]'\"=:(]|\./)$a([[:space:];&|'\")]|$)#\1__allowed__\2#g"); done
    for d in $DENY; do
      if echo "$CMD" | grep -qE "(^|[[:space:]'\"=:(]|\./)$d/" || bare_denied_word "$CMD" "$d" \
        || echo "$CMD" | grep -qE "[:=]$d(/|[[:space:];&|'\")]|$)"; then
        block "the command touches '$d'."
      fi
    done
    unset IFS
    ;;
esac

exit 0
