#!/bin/bash
# PreToolUse hook (foreman): keeps a long Markdown file from being loaded whole into context, as configured in
# .claude/foreman.json:
#   "docs": {"max_bytes": 20000, "exclude": ["CHANGELOG.md", "docs/decisions/*"]}
# With no "docs" key, this hook does nothing. exclude entries are repo-relative paths (and their subpaths) or
# globs, checked against every checkout of the repo (this one, the main checkout, and other worktrees, including a
# worktree nested under this repo, as under .claude/worktrees/), matched against the longest (most specific) base,
# the way lane-guard.sh does, since an excluded file can be reached through any of their paths.
#
# No hooks.json `timeout` here on purpose: a PreToolUse hook fails OPEN on timeout (the tool call proceeds as if
# the hook had passed), and the default is 600s anyway, far past what the fixes below need — a timeout would not
# have helped the slow-glob case this hook used to have, only hidden it later.
#
# Read: blocks (exit 2) a Read of a *.md/*.markdown/*.mdx file (any case) whose resolved byte count exceeds
# max_bytes: the whole file when neither offset nor limit is given; a 2000-line window from offset when only
# offset is given (Read's own default window); otherwise the requested range — unless the file is excluded.
# Bash, best effort: blocks cat/less/more/bat/tac/nl (plain, or via `command`/`xargs`) of an over-limit file, when
# its real content would reach the transcript: not when it's the target of a write redirect or a heredoc, not when
# its stdout is redirected to a file, and not when it only feeds a later pipe stage that doesn't itself just pass
# the bytes through (cat/tee/less/more/bat do; anything else, like grep or sed, does not). sed -n 'a,bp',
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
GLOB_MATCH_CAP=200                              # a wider glob argument is refused outright, not partly checked

# Physical path (resolves symlinks such as macOS /var -> /private/var), for paths that may not exist yet.
physical() {
  local d="$1" rest=""
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do rest="/$(basename "$d")$rest"; d=$(dirname "$d"); done
  echo "$(cd "$d" 2>/dev/null && pwd -P)$rest"
}

# Every checkout of this repo (this one, the main checkout, other worktrees — including one nested under this
# repo, as under .claude/worktrees/), as lane-guard.sh computes it, so an excluded or oversized file is recognised
# the same way regardless of which checkout's path reaches it.
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

# Exclude patterns are read once per hook run (not once per file: a wide glob can match thousands of files).
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

is_md() {  # is_md <path> -- true for .md, .markdown, .mdx; the extension is lowercased before the compare (so any
           # case matches), but the rest of the path is left alone, so excludes stay case-exact.
  local ext
  ext=$(printf '%s' "${1##*.}" | tr '[:upper:]' '[:lower:]')
  case "$ext" in md | markdown | mdx) return 0 ;; esac
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

block_msg() {  # block_msg <bytes> <path as the caller spelled it>
  echo "BLOCKED: '$2' is $1 bytes, over the docs guard's $MAX-byte limit (.claude/foreman.json › docs)." \
       "Search it with rg and Read a range (offset/limit) under $MAX bytes, or in the main session ask the foreman:doc-reader agent." >&2
  exit 2
}

check_file() {  # check_file <absolute path> <name to show in the message>
  # Cheapest checks first: a glob can match thousands of files, and excluded()/relpath() (a stat per checkout,
  # sometimes a subshell) cost far more than a plain `wc -c` on a file that turns out to be small anyway.
  [ -f "$1" ] || return 0
  local bytes; bytes=$(wc -c <"$1" 2>/dev/null)
  [ -n "$bytes" ] && [ "$bytes" -gt "$MAX" ] || return 0
  excluded "$(relpath "$1")" && return 0
  block_msg "$bytes" "$2"
}

check_arg() {  # check_arg <arg as written> -- expands a glob (capped) before checking each match
  local arg="$1" m count=0
  if [[ "$arg" == *[\*\?\[]* ]]; then
    while IFS= read -r m; do
      [ -n "$m" ] || continue
      count=$((count + 1))
      if [ "$count" -gt "$GLOB_MATCH_CAP" ]; then
        echo "BLOCKED: '$arg' matches more than $GLOB_MATCH_CAP files; name the file instead of a wide glob." >&2
        exit 2
      fi
      [[ "$m" == /* ]] || m="$EFFECTIVE_CWD/$m"
      check_file "$m" "$m"
    done < <(cd "$EFFECTIVE_CWD" 2>/dev/null && compgen -G "$arg")
  else
    local abs="$arg"; [[ "$abs" == /* ]] || abs="$EFFECTIVE_CWD/$arg"
    check_file "$abs" "$arg"
  fi
}

# split_statements <command text> -> one top-level statement per line, split on &&, ||, ; and a single & (a
# background job, like a pipe, runs in a way that doesn't carry a `cd` back to the rest of the script either).
# Content inside $(...), (...) or `...` is kept opaque (not split, and never exposed as its own statement), so a
# `cd` inside a subshell or command substitution is never mistaken for a top-level `cd`.
split_statements() {
  local s="$1" i=0 c c2 depth=0 backtick=0 buf="" n
  n=${#s}   # a separate statement: `local x=$1 n=${#x}` would compute n against x's OLD value, not this one's
  while [ "$i" -lt "$n" ]; do
    c="${s:$i:1}"
    if [ "$backtick" = 1 ]; then
      buf+="$c"; [ "$c" = '`' ] && backtick=0
      i=$((i + 1)); continue
    fi
    case "$c" in
      '`') backtick=1; buf+="$c"; i=$((i + 1)); continue ;;
      '(') depth=$((depth + 1)); buf+="$c"; i=$((i + 1)); continue ;;
      ')') [ "$depth" -gt 0 ] && depth=$((depth - 1)); buf+="$c"; i=$((i + 1)); continue ;;
    esac
    if [ "$depth" -eq 0 ]; then
      c2="${s:$i:2}"
      case "$c2" in
        '&&' | '||') printf '%s\n' "$buf"; buf=""; i=$((i + 2)); continue ;;
      esac
      case "$c" in
        ';') printf '%s\n' "$buf"; buf=""; i=$((i + 1)); continue ;;
        '&')
          case "$buf" in
            *'<' | *'>') ;;   # part of a redirect operator (>&, <&, N>&M): not a background job, don't split
            *) printf '%s\n' "$buf"; buf=""; i=$((i + 1)); continue ;;
          esac
          ;;
      esac
    fi
    buf+="$c"
    i=$((i + 1))
  done
  printf '%s\n' "$buf"
}

# classify_stage <stage text> -- sets CMDNAME (cat/less/more/bat/tac/nl/tee, or "" if not one of those), REAL_ARGS
# (the array of real positional arguments: not a flag, not a redirect operator or its target, an attached "<file"
# or "N<file" reduced to just the file), and HAS_OUT (1 if this stage's own stdout, fd 1, is redirected to a file).
classify_stage() {
  CMDNAME=""; REAL_ARGS=(); HAS_OUT=0
  local W i=0 j arg skip_next=0
  read -ra W <<<"$(printf '%s' "$1" | tr -d "\"'")"
  while [ $i -lt ${#W[@]} ] && [[ "${W[$i]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do i=$((i + 1)); done
  [ $i -lt ${#W[@]} ] || return 0
  case "${W[$i]}" in command | xargs) i=$((i + 1)) ;; esac   # `command cat x.md`, `xargs cat x.md`
  [ $i -lt ${#W[@]} ] || return 0
  case "${W[$i]##*/}" in
    cat | less | more | bat | tac | nl | tee) CMDNAME="${W[$i]##*/}" ;;
    *) return 0 ;;
  esac
  for ((j = i + 1; j < ${#W[@]}; j++)); do
    arg=${W[$j]}
    if [ "$skip_next" = 1 ]; then skip_next=0; continue; fi
    # stdout (fd 1, or no number) to a file: >, >>, 1>, 1>> -- a write, and the stage's output never reaches the
    # transcript raw, so its reads don't either (the same reason a feed into a pipe is allowed). The fd-dup/close
    # form (1>&2, >&-) is self-contained -- no following target word -- so it must NOT set skip_next; only the
    # plain form (>, 1>) expects one.
    if [[ "$arg" =~ ^1?\>{1,2}\&[0-9-]*$ ]]; then HAS_OUT=1; continue; fi
    if [[ "$arg" =~ ^1?\>{1,2}$ ]]; then HAS_OUT=1; skip_next=1; continue; fi
    if [[ "$arg" =~ ^1?\>{1,2} ]]; then HAS_OUT=1; continue; fi
    # a redirect to another fd (2>, 2>>, 2>&1, …): not stdout, and not a read of ours. Same self-contained-vs-bare
    # split: "2>&1" has no following target; a bare "2>" does.
    if [[ "$arg" =~ ^[2-9]\>{1,2}\&[0-9-]*$ ]]; then continue; fi
    if [[ "$arg" =~ ^[2-9]\>{1,2}$ ]]; then skip_next=1; continue; fi
    if [[ "$arg" =~ ^[2-9]\>{1,2} ]]; then continue; fi
    # heredoc / here-string (<<, <<-, <<<): inline content, never a file on disk.
    if [[ "$arg" =~ ^[0-9]*\<{2,3}-?$ ]]; then skip_next=1; continue; fi
    if [[ "$arg" =~ ^[0-9]*\<{2,3}-? ]]; then continue; fi
    # fd duplication/closing on the input side (N<&M, N<&-): self-contained, not a file.
    if [[ "$arg" =~ ^[0-9]*\<\&[0-9-]* ]]; then continue; fi
    # a genuine input redirect (<, N<): this IS a read, same as a positional filename.
    if [[ "$arg" =~ ^[0-9]*\<$ ]]; then continue; fi                        # next token is the real filename
    if [[ "$arg" =~ ^[0-9]*\<(.+)$ ]]; then arg="${BASH_REMATCH[1]}"; fi     # "<file"/"N<file": keep the file part
    case "$arg" in -*) continue ;; esac
    REAL_ARGS+=("$arg")
  done
  return 0
}

case "$TOOL" in
  Read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -n "$FILE" ] || exit 0
    is_md "$FILE" || exit 0
    ABS="$FILE"; [[ "$ABS" != /* ]] && ABS="${CWD:-.}/$FILE"
    [ -f "$ABS" ] || exit 0
    OFFSET=$(echo "$INPUT" | jq -r '.tool_input.offset // empty')
    LIMIT=$(echo "$INPUT" | jq -r '.tool_input.limit // empty')
    BYTES=$(range_bytes "$ABS" "$OFFSET" "$LIMIT")
    [ -n "$BYTES" ] && [ "$BYTES" -gt "$MAX" ] || exit 0
    excluded "$(relpath "$ABS")" && exit 0
    block_msg "$BYTES" "$FILE"
    ;;
  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    CMD=$(echo "$RAW" | awk -f "$HOOKS/lib/strip-heredocs.awk")
    EFFECTIVE_CWD="${CWD:-.}"
    while IFS= read -r statement; do
      [ -n "$statement" ] || continue
      trimmed=$(printf '%s' "$statement" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
      [ -n "$trimmed" ] || continue

      # Split into pipe stages first (best effort: not depth-aware), so a leading `cd` can only ever be the
      # *whole* statement, never one end of a pipe it doesn't really affect (`cd . | cat x.md` runs `cd` in a
      # subshell; it never changes this script's notion of the cwd either).
      STAGES=()
      while IFS= read -r stage; do STAGES+=("$stage"); done <<<"$(printf '%s' "$trimmed" | sed -E 's/\|/\n/g')"

      if [ "${#STAGES[@]}" -eq 1 ]; then
        only=$(printf '%s' "${STAGES[0]}" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
        case "$only" in
          cd\ *)   # track a simple preceding `cd <dir> &&`/`;` (best effort: no `~`, `$VAR`, `cd -`, or a failure
                   # can ever empty EFFECTIVE_CWD -- only a *successful* resolve overwrites it)
            newdir=$(printf '%s' "${only#cd }" | sed -E 's/^[[:space:]]+//; s/^["'\'']//; s/["'\'']$//')
            [[ "$newdir" == /* ]] || newdir="$EFFECTIVE_CWD/$newdir"
            resolved=$(cd "$newdir" 2>/dev/null && pwd -P)
            [ -n "$resolved" ] && EFFECTIVE_CWD="$resolved"
            continue
            ;;
        esac
      fi

      # Walk the pipeline from its last stage backward. A stage whose own output doesn't reach the transcript —
      # it writes to a file, or it's cat/tee/less/more/bat/nl/tac just passing stdin through with no file
      # argument of its own — means the *real* source is whatever feeds it, so look at the stage before it.
      # Anything else (an unrecognised command, or a recognised one with real file arguments) ends the walk.
      for ((k = ${#STAGES[@]} - 1; k >= 0; k--)); do
        classify_stage "${STAGES[$k]}"
        [ -n "$CMDNAME" ] || break                    # the pipeline's effect here isn't a raw file dump
        [ "$HAS_OUT" = 1 ] && break                    # this stage's output goes to a file, not the transcript
        if [ "$CMDNAME" = tee ] || [ "${#REAL_ARGS[@]}" -eq 0 ]; then
          continue   # a pure passthrough (reads stdin, writes stdout): look at what feeds it, if anything
        fi
        for a in "${REAL_ARGS[@]}"; do
          is_md "$a" || continue
          check_arg "$a"
        done
        break
      done
    done <<<"$(split_statements "$CMD")"
    ;;
esac

exit 0
