#!/bin/bash
# PostToolUse hook (foreman): formats an edited file with the project's own formatter, as configured in
# .claude/foreman.json:
#   "format": {"backend/": "uv run ruff format {file}", "frontend/src/": "pnpm exec prettier --write {file}"}
# The key is a repo-relative path prefix; the command runs from that folder of the checkout that holds the file (a
# story worktree or the main checkout), so the project's formatter config applies. Files outside every prefix are
# left alone. Never blocks: a formatter failure is reported to Claude as additional context and the edit stands.
#
# The command comes from the config of the session's project (CLAUDE_PROJECT_DIR), i.e. the reviewed, merged one,
# never from a story worktree's copy, so a story branch can't change what runs here. `story-finish` flags any
# story diff that touches this config, since `format` and `checks` are commands.

INPUT=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[ -n "$FILE" ] && [ -f "$FILE" ] || exit 0
ROOT=$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null) || exit 0
CONFIG="${CLAUDE_PROJECT_DIR:-$ROOT}/.claude/foreman.json"
[ -f "$CONFIG" ] || exit 0
ABS=$(cd "$(dirname "$FILE")" && pwd -P)/$(basename "$FILE")
ROOT=$(cd "$ROOT" && pwd -P)
REL=${ABS#"$ROOT"/}
[ "$REL" != "$ABS" ] || exit 0

while IFS=$'\t' read -r PREFIX COMMAND; do
  [ -n "$PREFIX" ] || continue
  PREFIX=${PREFIX%/}/
  case "$REL" in
    "$PREFIX"*)
      INNER=${REL#"$PREFIX"}
      RUN=${COMMAND//\{file\}/$(printf '%q' "$INNER")}
      if ! OUT=$(cd "$ROOT/$PREFIX" && bash -c "$RUN" 2>&1); then
        jq -n --arg msg "The formatter failed on $REL ('$RUN' in $PREFIX): $(printf '%s' "$OUT" | tail -5)" \
          '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $msg}}'
      fi
      break
      ;;
  esac
done <<<"$(jq -r '.format // {} | to_entries[] | "\(.key)\t\(.value)"' "$CONFIG")"
exit 0
