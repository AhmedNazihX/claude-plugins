#!/bin/bash
# PreToolUse hook (project): <one line: the rule, and its source, e.g. "decision 012">.
# Copied from the story-workflow plugin's template by the guardrails skill. Needs jq.
# Exit 2 blocks the tool call (stderr goes to Claude); exit 0 allows it.
# Test it in .claude/hooks/test-hooks.sh: one case it must block, one legitimate near-miss it must allow.

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

block() {
  echo "BLOCKED: $1 (rule: <rule>, see <source>). If you believe this is a legitimate exception, stop and ask the user." >&2
  exit 2
}

case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    # Example: never edit a generated file.
    # [[ "$FILE" == */generated/* ]] && block "$FILE is generated; change its source and regenerate."
    ;;
  Bash)
    # Example: migrations only through the tool.
    # echo "$CMD" | grep -qE 'touch .*migrations/' && block "create migrations with '<tool> migration new'."
    ;;
esac
exit 0
