#!/bin/bash
# PreToolUse hook (foreman): keeps a long Markdown file from being loaded whole into context, as configured in
# .claude/foreman.json:
#   "docs": {"max_bytes": 20000, "exclude": ["CHANGELOG.md", "docs/decisions/*"]}
# With no "docs" key, this hook does nothing. exclude entries are repo-relative paths (and their subpaths) or globs.
#
# Read: blocks (exit 2) a Read of a *.md file whose resolved byte count exceeds max_bytes — the whole file when no
# offset/limit is given, otherwise the requested line range — unless the file is excluded.
# Bash, best effort: blocks cat/less/more/bat/tac/nl of an over-limit *.md file, since none of them take a line
# range. sed -n 'a,bp', head/tail -n, rg/grep, wc, git diff/log/show and backlog.py are never blocked.

INPUT=$(cat)
HOOKS="$(cd "$(dirname "$0")" && pwd)"
command -v jq >/dev/null 2>&1 || { echo "BLOCKED: foreman's doc guard needs jq (brew install jq)." >&2; exit 2; }

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
CONFIG="${CLAUDE_PROJECT_DIR:-$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)}/.claude/foreman.json"
[ -f "$CONFIG" ] || exit 0
DOCS=$(jq -c '.docs // empty' "$CONFIG" 2>/dev/null)
[ -n "$DOCS" ] || exit 0
MAX=$(echo "$DOCS" | jq -r '.max_bytes // empty')
case "$MAX" in '' | *[!0-9]*) exit 0 ;; esac   # no usable limit configured: nothing to enforce

# Physical path (resolves symlinks such as macOS /var -> /private/var), for paths that may not exist yet.
physical() {
  local d="$1" rest=""
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do rest="/$(basename "$d")$rest"; d=$(dirname "$d"); done
  echo "$(cd "$d" 2>/dev/null && pwd -P)$rest"
}
ROOT=$(physical "$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null || echo "${CWD:-.}")")

relpath() {  # relpath <absolute path> -> repo-relative, or the absolute path if outside the repo
  local p
  p=$(physical "$1")
  case "$p" in
    "$ROOT") echo "." ;;
    "$ROOT"/*) echo "${p#"$ROOT"/}" ;;
    *) echo "$p" ;;
  esac
}

excluded() {  # excluded <repo-relative path>
  local rel="$1" pat IFS=$'\n'
  for pat in $(echo "$DOCS" | jq -r '.exclude // [] | .[]'); do
    pat=${pat#/}; pat=${pat%/}
    case "$rel" in $pat | $pat/*) return 0 ;; esac
  done
  return 1
}

range_bytes() {  # range_bytes <file> <offset> <limit> -> bytes the read would load
  local file="$1" offset="$2" limit="$3" start end
  if [ -z "$offset" ] && [ -z "$limit" ]; then
    wc -c <"$file" 2>/dev/null
    return
  fi
  start=${offset:-1}
  case "$start" in '' | *[!0-9]*) start=1 ;; esac
  [ "$start" -lt 1 ] && start=1
  if [ -n "$limit" ]; then
    end=$((start + limit - 1))
    sed -n "${start},${end}p" "$file" 2>/dev/null | wc -c
  else
    sed -n "${start},\$p" "$file" 2>/dev/null | wc -c
  fi
}

block_msg() {  # block_msg <bytes> <path as the caller spelled it>
  echo "BLOCKED: '$2' is $1 bytes, over the docs guard's $MAX-byte limit (.claude/foreman.json › docs)." \
       "Search it with rg and Read a range (offset/limit) under $MAX bytes, or in the main session ask the doc-reader agent." >&2
  exit 2
}

case "$TOOL" in
  Read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -n "$FILE" ] || exit 0
    case "$FILE" in *.md | *.MD) ;; *) exit 0 ;; esac
    ABS="$FILE"; [[ "$ABS" != /* ]] && ABS="${CWD:-.}/$ABS"
    [ -f "$ABS" ] || exit 0
    excluded "$(relpath "$ABS")" && exit 0
    OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty')
    LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty')
    BYTES=$(range_bytes "$ABS" "$OFFSET" "$LIMIT")
    [ -n "$BYTES" ] && [ "$BYTES" -gt "$MAX" ] && block_msg "$BYTES" "$FILE"
    ;;
  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    CMD=$(echo "$RAW" | awk -f "$HOOKS/lib/strip-heredocs.awk")
    while IFS= read -r part; do
      read -ra W <<<"$(printf '%s' "$part" | tr -d "\"'")"
      i=0
      while [ $i -lt ${#W[@]} ] && [[ "${W[$i]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do i=$((i + 1)); done
      [ $i -lt ${#W[@]} ] || continue
      case "${W[$i]##*/}" in
        cat | less | more | bat | tac | nl) ;;
        *) continue ;;
      esac
      for ((j = i + 1; j < ${#W[@]}; j++)); do
        arg=${W[$j]}
        case "$arg" in
          -*) continue ;;
          *.md | *.MD) ;;
          *) continue ;;
        esac
        ABS="$arg"; [[ "$ABS" != /* ]] && ABS="${CWD:-.}/$ABS"
        [ -f "$ABS" ] || continue
        excluded "$(relpath "$ABS")" && continue
        BYTES=$(wc -c <"$ABS" 2>/dev/null)
        [ -n "$BYTES" ] && [ "$BYTES" -gt "$MAX" ] && block_msg "$BYTES" "$arg"
      done
    done <<<"$(printf '%s\n' "$CMD" | sed -E 's/(\&\&|\|\||;|\||\$\(|\(|\)|`)/\n/g')"
    ;;
esac

exit 0
