#!/bin/bash
# PreToolUse hook (foreman): keeps a long Markdown file from being loaded whole into context, as configured in
# .claude/foreman.json:
#   "docs": {"max_bytes": 20000, "exclude": ["CHANGELOG.md", "docs/decisions/*"]}
# With no "docs" key, this hook does nothing. exclude entries are repo-relative paths (and their subpaths) or
# globs, checked against every checkout of the repo (this one, the main checkout, and other worktrees, including a
# worktree nested under this repo, as under .claude/worktrees/), matched against the longest (most specific) base,
# the way lane-guard.sh does, since an excluded file can be reached through any of their paths.
#
# This guards the Read tool only, and is exact: it blocks (exit 2) a Read of a *.md/*.markdown/*.mdx file (any
# case) whose resolved byte count exceeds max_bytes — the whole file when neither offset nor limit is given; a
# 2000-line window from offset when only offset is given (Read's own default window); otherwise the requested
# range — unless the file is excluded.
#
# It does not look at Bash at all: a shell command that cats, greps or otherwise reads a file is not checked here.
# Earlier drafts tried to parse shell commands for this (quoting, redirects, pipes, cd, subshells, …); each attempt
# either missed a real read or was slow enough on a long command to be a problem in its own right, for a part of
# the guard that was never exact to begin with. The `doc-reader` agent and the project's own rule against reading a
# long file whole are what cover a shell-based lookup instead.

INPUT=$(cat)
command -v jq >/dev/null 2>&1 || { echo "BLOCKED: foreman's doc guard needs jq (brew install jq)." >&2; exit 2; }

TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
[ "$TOOL" = Read ] || exit 0
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
CONFIG="${CLAUDE_PROJECT_DIR:-$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null)}/.claude/foreman.json"
[ -f "$CONFIG" ] || exit 0
DOCS=$(jq -c '.docs // empty' "$CONFIG" 2>/dev/null)
[ -n "$DOCS" ] || exit 0
MAX=$(echo "$DOCS" | jq -r '.max_bytes // empty')
case "$MAX" in '' | *[!0-9]*) exit 0 ;; esac   # no usable limit configured: nothing to enforce
READ_DEFAULT_LINES=2000                        # Read's own default window when only `offset` is given

FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -n "$FILE" ] || exit 0

is_md() {  # is_md <path> -- true for .md, .markdown, .mdx, any case. Toggles nocasematch locally (restored
           # before returning) rather than forking a subshell and `tr`; excludes stay case-exact regardless,
           # since excluded() never turns nocasematch on.
  local was=0
  shopt -q nocasematch && was=1
  shopt -s nocasematch
  case "$1" in
    *.md | *.markdown | *.mdx) [ "$was" = 1 ] || shopt -u nocasematch; return 0 ;;
  esac
  [ "$was" = 1 ] || shopt -u nocasematch
  return 1
}
is_md "$FILE" || exit 0
ABS="$FILE"; [[ "$ABS" != /* ]] && ABS="${CWD:-.}/$FILE"
[ -f "$ABS" ] || exit 0

# Physical path (resolves symlinks such as macOS /var -> /private/var), for paths that may not exist yet.
physical() {
  local d="$1" rest=""
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do rest="/$(basename "$d")$rest"; d=$(dirname "$d"); done
  echo "$(cd "$d" 2>/dev/null && pwd -P)$rest"
}

# Every checkout of this repo (this one, the main checkout, other worktrees — including one nested under this
# repo, as under .claude/worktrees/), as lane-guard.sh computes it, so an excluded file is recognised the same way
# regardless of which checkout's path reaches it.
ROOT=$(physical "$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null || echo "${CWD:-.}")")
MAIN=$(cd "$(dirname "$(git -C "${CWD:-.}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)")" 2>/dev/null && pwd -P)
OTHERS=$(git -C "${CWD:-.}" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | while IFS= read -r w; do
  (cd "$w" 2>/dev/null && pwd -P); done | grep -vxF "$ROOT")
BASES=$(printf '%s\n%s\n%s\n' "$ROOT" "$MAIN" "$OTHERS" | awk 'NF && !seen[$0]++')

relpath() {  # relpath <absolute path> -> repo-relative, against the LONGEST-matching checkout (one can be nested
             # inside another, e.g. a worktree under .claude/worktrees/, so the first match isn't always right)
  local p base best="" bestlen=-1
  p=$(physical "$1")
  while IFS= read -r base; do
    [ -n "$base" ] || continue
    if [ "$p" = "$base" ]; then echo "."; return; fi
    case "$p" in "$base"/*) [ "${#base}" -gt "$bestlen" ] && { best="$base"; bestlen=${#base}; } ;; esac
  done <<<"$BASES"
  [ "$bestlen" -ge 0 ] && { echo "${p#"$best"/}"; return; }
  echo "$p"
}

# Exclude patterns are read once per hook run.
EXCLUDE_PATTERNS=()
while IFS= read -r pat; do
  [ -n "$pat" ] || continue
  pat=${pat#/}; pat=${pat%/}
  EXCLUDE_PATTERNS+=("$pat")
done < <(echo "$DOCS" | jq -r '.exclude // [] | .[]')

excluded() {  # excluded <repo-relative path>
  local rel="$1" pat
  for pat in "${EXCLUDE_PATTERNS[@]}"; do
    case "$rel" in $pat | $pat/*) return 0 ;; esac
  done
  return 1
}

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

OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty')
LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty')
BYTES=$(range_bytes "$ABS" "$OFFSET" "$LIMIT")
[ -n "$BYTES" ] && [ "$BYTES" -gt "$MAX" ] || exit 0
excluded "$(relpath "$ABS")" && exit 0

echo "BLOCKED: '$FILE' is $BYTES bytes, over the docs guard's $MAX-byte limit (.claude/foreman.json › docs)." \
     "Search it with rg and Read a range (offset/limit) under $MAX bytes, or in the main session ask the foreman:doc-reader agent." >&2
exit 2
