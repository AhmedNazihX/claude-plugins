#!/bin/bash
# Regression tests for the foreman doc guard hook (doc-guard.sh).
# Run: bash hooks/test-doc-guard.sh   (from the plugin root)
# Builds a throwaway repo with its own config and markdown files; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks/lib" "$R/docs/decisions"
cp "$SRC/doc-guard.sh" "$R/.claude/hooks/"
cp "$SRC/lib/strip-heredocs.awk" "$R/.claude/hooks/lib/"
git -C "$R" init -q

python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/BIG.md"  # 150 lines, 30150 bytes total
printf 'small file\n' >"$R/docs/SMALL.md"                                   # under the limit
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/decisions/001-x.md"  # excluded, also over the limit
printf 'plain text, not markdown\n' >"$R/NOTES.txt"
git -C "$R" add -A && git -C "$R" commit -q -m init

run() {  # run <expected exit> <json> <label>
  printf '%s' "$2" | "$GUARD" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$1" ]; then echo "  ok    $3"; else echo "  FAIL  $3 (exit $c, want $1)"; FAILS=$((FAILS + 1)); fi
}
read_in() { jq -nc --arg d "$1" --arg p "$2" --argjson o "${3:-null}" --argjson l "${4:-null}" \
  '{tool_name:"Read",cwd:$d,tool_input:({file_path:$p} + (if $o == null then {} else {offset:$o} end) + (if $l == null then {} else {limit:$l} end))}'; }
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }

GUARD="$R/.claude/hooks/doc-guard.sh"

echo "inactive: no 'docs' key in the config"
run 0 "$(read_in "$R" "$R/docs/BIG.md")"                        "no config at all: Read of the big file"

cat >"$R/.claude/foreman.json" <<'JSON'
{"docs": {"max_bytes": 20000, "exclude": ["docs/decisions"]}}
JSON
export CLAUDE_PROJECT_DIR="$R"

echo "active: 'docs' key present (max_bytes 20000)"
run 0 "$(read_in "$R" "$R/docs/SMALL.md")"                      "small .md allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md")"                        "large .md blocked whole"
run 0 "$(read_in "$R" "$R/docs/BIG.md" 1 50)"                   "range under the limit allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md" 1 15000)"                "range over the limit blocked"
run 0 "$(read_in "$R" "$R/docs/decisions/001-x.md")"            "excluded file allowed, even though it's large"
run 0 "$(read_in "$R" "$R/NOTES.txt")"                          "non-.md file allowed"
run 2 "$(bash_in "$R" "cat docs/BIG.md")"                       "Bash cat of the large file blocked"
run 0 "$(bash_in "$R" "sed -n '1,5p' docs/BIG.md")"             "Bash sed -n allowed"
run 0 "$(bash_in "$R" "rg -n foo docs/BIG.md")"                 "Bash rg allowed"
run 0 "$(bash_in "$R" "head -n 5 docs/BIG.md")"                 "Bash head -n allowed"
run 0 "$(bash_in "$R" "wc -l docs/BIG.md")"                     "Bash wc allowed"
run 0 "$(bash_in "$R" "git diff docs/BIG.md")"                  "Bash git diff allowed"
run 0 "$(bash_in "$R" "cat docs/SMALL.md")"                     "Bash cat of a small file allowed"
run 2 "$(bash_in "$R" "less docs/BIG.md")"                      "Bash less of the large file blocked"

echo
[ "$FAILS" = 0 ] && echo "All doc guard tests passed." || { echo "$FAILS doc guard test(s) failed."; exit 1; }
