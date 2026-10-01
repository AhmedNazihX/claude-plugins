#!/bin/bash
# PreToolUse hook (foreman): keeps a long Markdown file from being loaded whole into context, as configured in
# .claude/foreman.json:
#   "docs": {"max_bytes": 20000, "exclude": ["CHANGELOG.md", "docs/decisions/*"]}
# With no "docs" key, this hook does nothing. exclude entries are repo-relative paths (and their subpaths) or
# globs, checked against every checkout of the repo (this one, the main checkout, and other worktrees), the way
# lane-guard.sh does, since an excluded file can be reached through any of their paths.
#
# Read: blocks (exit 2) a Read of a *.md/*.markdown/*.mdx file (any case) whose resolved byte count exceeds
# max_bytes: the whole file when neither offset nor limit is given; a 2000-line window from offset when only
# offset is given (Read's own default window); otherwise the requested range — unless the file is excluded.
# Bash, best effort: blocks cat/less/more/bat/tac/nl (plain, or via `command`/`xargs`) of an over-limit file, when
# its output isn't fed into a pipe and it isn't the target of a write redirect or a heredoc. sed -n 'a,bp',
# head/tail -n, rg/grep, wc, git diff/log/show and backlog.py are never blocked. A range under the limit is fine;
# this side is best effort, not exact, so it can still be worked around on purpose.

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
READ_DEFAULT_LINES=2000                        # Read's own default window when only `offset` is given
shopt -s nocasematch                           # .md/.MD/.Md, .markdown, .mdx all count

# Physical path (resolves symlinks such as macOS /var -> /private/var), for paths that may not exist yet.
physical() {
  local d="$1" rest=""
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do rest="/$(basename "$d")$rest"; d=$(dirname "$d"); done
  echo "$(cd "$d" 2>/dev/null && pwd -P)$rest"
}

# Every checkout of this repo (this one, the main checkout, other worktrees), as lane-guard.sh computes it, so an
# excluded or oversized file is recognised the same way regardless of which checkout's path reaches it.
ROOT=$(physical "$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null || echo "${CWD:-.}")")
MAIN=$(cd "$(dirname "$(git -C "${CWD:-.}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")" 2>/dev/null && pwd -P)
OTHERS=$(git -C "${CWD:-.}" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | while IFS= read -r w; do
  (cd "$w" 2>/dev/null && pwd -P); done | grep -vxF "$ROOT")
BASES=$(printf '%s\n%s\n%s\n' "$ROOT" "$MAIN" "$OTHERS" | awk 'NF && !seen[$0]++')

relpath() {  # relpath <absolute path> -> repo-relative (against whichever checkout holds it), or itself
  local p base
  p=$(physical "$1")
  while IFS= read -r base; do
    [ -n "$base" ] || continue
    [ "$p" = "$base" ] && { echo "."; return; }
    case "$p" in "$base"/*) echo "${p#"$base"/}"; return ;; esac
  done <<<"$BASES"
  echo "$p"
}

excluded() {  # excluded <repo-relative path>
  local rel="$1" pat
  while IFS= read -r pat; do
    [ -n "$pat" ] || continue
    pat=${pat#/}; pat=${pat%/}
    case "$rel" in $pat | $pat/*) return 0 ;; esac
  done < <(echo "$DOCS" | jq -r '.exclude // [] | .[]')
  return 1
}

is_md() { case "$1" in *.md | *.markdown | *.mdx) return 0 ;; esac; return 1; }

digits_only() { case "$1" in '' | *[!0-9]*) return 1 ;; esac; }

range_bytes() {  # range_bytes <file> <offset> <limit> -> bytes the read would load
  local file="$1" offset="$2" limit="$3" start end
  digits_only "$offset" || offset=""   # a non-digit offset/limit (however it got here) is never used in arithmetic
  digits_only "$limit" || limit=""
  if [ -z "$offset" ] && [ -z "$limit" ]; then
    wc -c <"$file" 2>/dev/null
    return
  fi
  start=${offset:-1}
  [ "$start" -lt 1 ] && start=1
  if [ -n "$limit" ]; then
    end=$((start + limit - 1))
  else
    end=$((start + READ_DEFAULT_LINES - 1))   # offset given, no limit: Read's own default window applies
  fi
  sed -n "${start},${end}p;${end}q" "$file" 2>/dev/null | wc -c
}

block_msg() {  # block_msg <bytes> <path as the caller spelled it>
  echo "BLOCKED: '$2' is $1 bytes, over the docs guard's $MAX-byte limit (.claude/foreman.json › docs)." \
       "Search it with rg and Read a range (offset/limit) under $MAX bytes, or in the main session ask the foreman:doc-reader agent." >&2
  exit 2
}

check_file() {  # check_file <absolute path> <name to show in the message>
  [ -f "$1" ] || return 0
  excluded "$(relpath "$1")" && return 0
  local bytes; bytes=$(wc -c <"$1" 2>/dev/null)
  [ -n "$bytes" ] && [ "$bytes" -gt "$MAX" ] && block_msg "$bytes" "$2"
  return 0
}

case "$TOOL" in
  Read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -n "$FILE" ] || exit 0
    is_md "$FILE" || exit 0
    ABS="$FILE"; [[ "$ABS" != /* ]] && ABS="${CWD:-.}/$FILE"
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
    EFFECTIVE_CWD="${CWD:-.}"
    while IFS= read -r statement; do
      [ -n "$statement" ] || continue
      trimmed=$(printf '%s' "$statement" | sed -E 's/^[[:space:]]+|[[:space:]]+$//')
      case "$trimmed" in
        cd\ *)   # track a simple preceding `cd <dir> &&` (best effort: no subshells, no `cd -`, no `$(...)`)
          newdir=$(printf '%s' "${trimmed#cd }" | sed -E 's/^[[:space:]]+//; s/^["'\'']//; s/["'\'']$//')
          [[ "$newdir" == /* ]] || newdir="$EFFECTIVE_CWD/$newdir"
          EFFECTIVE_CWD=$(cd "$newdir" 2>/dev/null && pwd -P) || EFFECTIVE_CWD="$EFFECTIVE_CWD"
          continue
          ;;
      esac
      # Only the last stage of a pipeline is checked: a `cat` that feeds a pipe isn't read into the transcript.
      last_stage=""
      while IFS= read -r stage; do last_stage="$stage"; done <<<"$(printf '%s' "$trimmed" | sed -E 's/\|/\n/g')"
      [ -n "$last_stage" ] || continue
      read -ra W <<<"$(printf '%s' "$last_stage" | tr -d "\"'")"
      i=0
      while [ $i -lt ${#W[@]} ] && [[ "${W[$i]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do i=$((i + 1)); done
      [ $i -lt ${#W[@]} ] || continue
      case "${W[$i]}" in command | xargs) i=$((i + 1)) ;; esac   # `command cat x.md`, `xargs cat x.md`
      [ $i -lt ${#W[@]} ] || continue
      case "${W[$i]##*/}" in
        cat | less | more | bat | tac | nl) ;;
        *) continue ;;
      esac
      skip_next=0
      for ((j = i + 1; j < ${#W[@]}; j++)); do
        arg=${W[$j]}
        if [ "$skip_next" = 1 ]; then skip_next=0; continue; fi
        if [[ "$arg" =~ ^[0-9]*(\>{1,2}|\<{1,2}-?)(\&[0-9]*)?$ ]]; then
          skip_next=1; continue        # a bare redirect operator: its target (next word) isn't a read of it
        fi
        if [[ "$arg" =~ ^[0-9]*(\>{1,2}|\<{1,2}-?) ]]; then
          continue                     # an attached-form redirect (>f, >>f, <f, 2>f, <<EOF, <<-EOF): not a read
        fi
        case "$arg" in -*) continue ;; esac
        is_md "$arg" || continue
        if [[ "$arg" == *[\*\?\[]* ]]; then
          while IFS= read -r m; do
            [ -n "$m" ] || continue
            [[ "$m" == /* ]] || m="$EFFECTIVE_CWD/$m"
            check_file "$m" "$m"
          done < <(cd "$EFFECTIVE_CWD" 2>/dev/null && compgen -G "$arg")
        else
          ABS="$arg"; [[ "$ABS" == /* ]] || ABS="$EFFECTIVE_CWD/$arg"
          check_file "$ABS" "$arg"
        fi
      done
    done <<<"$(printf '%s\n' "$CMD" | sed -E 's/(\&\&|\|\||;|\$\(|\(|\)|`)/\n/g')"
    ;;
esac

exit 0
