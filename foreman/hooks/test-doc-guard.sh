#!/bin/bash
# Regression tests for the foreman doc guard hook (doc-guard.sh).
# Run: bash hooks/test-doc-guard.sh   (from the plugin root)
# Builds a throwaway repo (plus extra worktrees) with its own config and markdown files; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks/lib" "$R/docs/decisions" "$R/docs/other" "$R/sub" "$R/CaseTest"
cp "$SRC/doc-guard.sh" "$R/.claude/hooks/"
cp "$SRC/lib/strip-heredocs.awk" "$R/.claude/hooks/lib/"

python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/BIG.md"            # 150 lines, 30150 bytes
printf 'small file\n' >"$R/docs/SMALL.md"                                            # under the limit
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/decisions/001-x.md"  # excluded, also over
python3 -c "print(('y' * 200 + chr(10)) * 150, end='')" >"$R/docs/other/BIGGER.md"   # excluded by a glob
python3 -c "print(('z' * 5 + chr(10)) * 10000, end='')" >"$R/docs/HUGE.md"           # 10000 lines, 5 bytes each: a
                                                                                      # whole read-to-EOF from any
                                                                                      # offset would be way over the
                                                                                      # limit, but Read's own 2000-
                                                                                      # line default window is not.
printf 'plain text, not markdown\n' >"$R/NOTES.txt"
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/BIG.MARKDOWN"
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/big.mdx"
printf 'small readme\n' >"$R/README.md"                                             # true top-level, small
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/CaseTest/BIG.md"        # for the case-exact test
git -C "$R" init -q && git -C "$R" add -A && git -C "$R" commit -q -m init

run() {  # run <expected exit> <json> <label>
  printf '%s' "$2" | "$GUARD" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$1" ]; then echo "  ok    $3"; else echo "  FAIL  $3 (exit $c, want $1)"; FAILS=$((FAILS + 1)); fi
}
read_in() { jq -nc --arg d "$1" --arg p "$2" --argjson o "${3:-null}" --argjson l "${4:-null}" \
  '{tool_name:"Read",cwd:$d,tool_input:({file_path:$p} + (if $o == null then {} else {offset:$o} end) + (if $l == null then {} else {limit:$l} end))}'; }
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
read_str_limit() {  # read_in, but $3 is forced to be a JSON *string* (not a number) -- for the injection payload
  jq -nc --arg d "$1" --arg p "$2" --arg l "$3" '{tool_name:"Read",cwd:$d,tool_input:{file_path:$p, limit:$l}}'
}

GUARD="$R/.claude/hooks/doc-guard.sh"

echo "inactive: no 'docs' key in the config"
run 0 "$(read_in "$R" "$R/docs/BIG.md")"                        "no config at all: Read of the big file"

cat >"$R/.claude/foreman.json" <<'JSON'
{"docs": {"max_bytes": 20000, "exclude": ["docs/decisions", "docs/other/*.md", "casetest/big.md"]}}
JSON
export CLAUDE_PROJECT_DIR="$R"

echo "active: 'docs' key present (max_bytes 20000)"
run 0 "$(read_in "$R" "$R/docs/SMALL.md")"                      "small .md allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md")"                        "large .md blocked whole"
run 0 "$(read_in "$R" "$R/docs/BIG.md" 1 50)"                   "range under the limit allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md" 1 15000)"                "range over the limit blocked"
run 0 "$(read_in "$R" "$R/docs/decisions/001-x.md")"            "excluded file (literal path) allowed, even though it's large"
run 0 "$(read_in "$R" "$R/docs/other/BIGGER.md")"               "excluded file (glob 'docs/other/*.md') allowed"
run 0 "$(read_in "$R/docs" "$R/docs/other/BIGGER.md")"          "same glob exclude allowed from a different cwd"
run 0 "$(read_in "$R" "$R/NOTES.txt")"                          "non-.md file allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.MARKDOWN")"                  ".MARKDOWN (any case) blocked whole like .md"
run 2 "$(read_in "$R" "$R/docs/big.mdx")"                       ".mdx blocked whole like .md"
run 2 "$(read_in "$R" "$R/CaseTest/BIG.md")"                    "exclude is case-exact: 'casetest/big.md' doesn't exempt 'CaseTest/BIG.md'"

echo "offset/limit edge cases"
run 0 "$(read_in "$R" "docs/SMALL.md")"                         "relative Read path (small file) allowed"
run 2 "$(read_in "$R" "docs/BIG.md")"                           "relative Read path (big file) blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 1 null)"                "offset-only: capped at Read's 2000-line default window (allowed)"
run 2 "$(read_in "$R" "$R/docs/HUGE.md")"                       "neither offset nor limit: the whole (over-limit) file blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" null 50)"               "limit-only (offset omitted): allowed"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 9500 null)"             "offset near EOF, no limit: allowed"

echo "limit/offset injection payload (security fix 1, round 1)"
MARK="$TMP/pwned-marker"
rm -f "$MARK"
PAYLOAD='1$(touch '"$MARK"')'
run 0 "$(read_str_limit "$R" "$R/docs/SMALL.md" "$PAYLOAD")"    "a non-digit limit payload is treated as absent, not evaluated"
if [ -e "$MARK" ]; then echo "  FAIL  the injection payload created a file"; FAILS=$((FAILS + 1))
else echo "  ok    the injection payload created no file"; fi

echo "Bash, best effort"
run 2 "$(bash_in "$R" "cat docs/BIG.md")"                       "Bash cat of the large file blocked"
run 0 "$(bash_in "$R" "sed -n '1,5p' docs/BIG.md")"             "Bash sed -n allowed"
run 0 "$(bash_in "$R" "rg -n foo docs/BIG.md")"                 "Bash rg allowed"
run 0 "$(bash_in "$R" "head -n 5 docs/BIG.md")"                 "Bash head -n allowed"
run 0 "$(bash_in "$R" "wc -l docs/BIG.md")"                     "Bash wc allowed"
run 0 "$(bash_in "$R" "git diff docs/BIG.md")"                  "Bash git diff allowed"
run 0 "$(bash_in "$R" "cat docs/SMALL.md")"                     "Bash cat of a small file allowed"
run 2 "$(bash_in "$R" "less docs/BIG.md")"                      "Bash less of the large file blocked"
run 2 "$(bash_in "$R" "command cat docs/BIG.md")"               "'command cat' blocked like cat"
run 2 "$(bash_in "$R" "xargs cat docs/BIG.md")"                 "'xargs cat' blocked like cat"
run 2 "$(bash_in "$R" "cd docs && cat BIG.md")"                 "a tracked preceding 'cd docs &&' still resolves the relative path"
run 0 "$(bash_in "$R" "cat docs/other/BIGGER.md")"              "Bash cat of a glob-excluded file allowed"

echo "redirects and pipes (fix round 1, item 7; round 2 regression + fixes, items 5/6/9)"
run 0 "$(bash_in "$R" 'cat >> docs/BIG.md <<EOF
line
EOF')"                                                          "cat >> BIG.md <<EOF (append, a write) allowed"
run 0 "$(bash_in "$R" "cat > docs/BIG.md")"                     "cat > BIG.md (overwrite, a write) allowed"
run 2 "$(bash_in "$R" "cat < docs/BIG.md")"                     "cat < BIG.md (a real read; was wrongly allowed) blocked"
run 2 "$(bash_in "$R" "cat <docs/BIG.md")"                      "cat <docs/BIG.md (attached, a real read) blocked"
run 0 "$(bash_in "$R" "cat docs/BIG.md | grep x")"              "cat BIG.md | grep x (feeds a pipe) allowed"
run 2 "$(bash_in "$R" "cat docs/BIG.md 2>/dev/null")"           "cat BIG.md 2>/dev/null (still a real read) blocked"
run 2 "$(bash_in "$R" "cat 2>&1 docs/BIG.md")"                  "cat 2>&1 docs/BIG.md (fd-dup has no target) still blocked"
run 0 "$(bash_in "$R" "cat docs/*.md > /tmp/foreman-test-all.txt")" "cat docs/*.md > file (stdout to a file) allowed"
run 0 "$(bash_in "$R" "cat docs/BIG.md > copy.md")"             "cat docs/BIG.md > copy.md (stdout to a file) allowed"

echo "glob argument expansion (bypass hardening)"
run 2 "$(bash_in "$R" "cat docs/*.md")"                         "cat docs/*.md expands and catches the over-limit match"
run 0 "$(bash_in "$R" "cat docs/other/*.md")"                   "cat docs/other/*.md expands to only excluded matches"

echo "pass-through pipeline stages (item 8)"
run 2 "$(bash_in "$R" "cat docs/BIG.md | cat")"                 "cat BIG.md | cat (passthrough) still blocked"
run 2 "$(bash_in "$R" "cat docs/BIG.md | tee")"                 "cat BIG.md | tee (passthrough) still blocked"
run 2 "$(bash_in "$R" "cat docs/BIG.md | less")"                "cat BIG.md | less (passthrough) still blocked"
run 2 "$(bash_in "$R" "cat docs/BIG.md | more")"                "cat BIG.md | more (passthrough) still blocked"
run 0 "$(bash_in "$R" "cat docs/BIG.md | grep x | cat")"        "cat BIG.md | grep x | cat (grep breaks the chain) allowed"
run 0 "$(bash_in "$R" "cat docs/SMALL.md | cat")"               "cat SMALL.md | cat (passthrough of a small file) allowed"

echo "cd tracking: a statement can't swallow its pipe or background job (item 7)"
run 2 "$(bash_in "$R" "cd . | cat docs/BIG.md")"                "cd . | cat BIG.md (cd doesn't swallow the pipe) blocked"
run 2 "$(bash_in "$R" "cd docs & cat BIG.md")"                  "cd docs & cat BIG.md (cd doesn't swallow the background job) blocked"

echo "cd tracking fixes (item 3)"
run 2 "$(bash_in "$R" "true && cd docs && cat BIG.md")"         "a cd in second position is still tracked (trim fix)"
run 2 "$(bash_in "$R" "cd /does/not/exist; cat docs/BIG.md")"  "a failed cd leaves the original cwd in place (temp-var fix)"
run 2 "$(bash_in "$R" "cd ~ && cd $R/docs && cat BIG.md")"      "cd ~ (fails) then cd /abs (succeeds): the absolute one wins"

echo "a cd inside \$(...) never leaks to a later statement (item 4)"
run 0 "$(bash_in "$R" 'X=$(cd sub && pwd); cat README.md')"     "leaked cd would resolve a real top-level file; not leaked, allowed"
run 2 "$(bash_in "$R" 'X=$(cd docs && pwd); cat docs/BIG.md')"  "leaked cd would misresolve docs/docs/BIG.md (old bug allowed this); not leaked, blocked"

echo "performance and the glob match cap (item 1)"
# A file count UNDER the 200-match cap, so this proves the per-file reordering is fast -- not that the cap just
# refused the whole thing outright (that's the separate, deliberately-blocked case right after).
mkdir -p "$R/docs/many" "$R/docs/toomany"
for i in $(seq 1 150); do printf 'f%d\n' "$i" >"$R/docs/many/f$i.md"; done
for i in $(seq 1 250); do printf 'g%d\n' "$i" >"$R/docs/toomany/g$i.md"; done
SECONDS=0
run 0 "$(bash_in "$R" "cat docs/many/*.md")"                    "150 small files via a glob (under the cap), all under the byte limit: allowed"
ELAPSED=$SECONDS
if [ "$ELAPSED" -le 2 ]; then echo "  ok    150 files checked in ${ELAPSED}s (well under budget)"
else echo "  FAIL  150 files took ${ELAPSED}s (too slow)"; FAILS=$((FAILS + 1)); fi
SECONDS=0
OUT=$(printf '%s' "$(bash_in "$R" "cat docs/toomany/*.md")" | "$GUARD" 2>&1)
RC=$?
ELAPSED=$SECONDS
if [ "$RC" = 2 ] && printf '%s' "$OUT" | grep -qi "too many\|matches more than"; then echo "  ok    a glob matching 250 files is refused outright (cap), in ${ELAPSED}s"
else echo "  FAIL  glob cap (exit $RC, ${ELAPSED}s): $OUT"; FAILS=$((FAILS + 1)); fi
if [ "$ELAPSED" -le 2 ]; then echo "  ok    hitting the cap is itself fast (this is what used to take 126s)"
else echo "  FAIL  hitting the cap took ${ELAPSED}s (should bail out as soon as the cap is crossed)"; FAILS=$((FAILS + 1)); fi

echo "missing jq (simulated via PATH)"
NOJQ="$TMP/no-jq-bin"
mkdir -p "$NOJQ"
for tool in git sed awk wc tr cat dirname basename grep; do
  p=$(command -v "$tool" 2>/dev/null) && ln -sf "$p" "$NOJQ/$tool"
done
OUT=$(printf '%s' "$(read_in "$R" "$R/docs/SMALL.md")" | PATH="$NOJQ" "$GUARD" 2>&1)
RC=$?
if [ "$RC" = 2 ] && printf '%s' "$OUT" | grep -q "needs jq"; then echo "  ok    missing jq fails closed"
else echo "  FAIL  missing jq (exit $RC): $OUT"; FAILS=$((FAILS + 1)); fi

echo "cross-checkout exclude and size, a sibling worktree (item 6, round 1)"
W="$TMP/worktree2"
git -C "$R" worktree add -q "$W" -b wt2-branch >/dev/null 2>&1
run 0 "$(read_in "$R" "$W/docs/decisions/001-x.md")"            "excluded file via a worktree's path, cwd = main checkout"
run 0 "$(read_in "$W" "$R/docs/decisions/001-x.md")"            "excluded file via the main checkout's path, cwd = worktree"
run 2 "$(read_in "$W" "$R/docs/BIG.md")"                        "non-excluded big file still blocked via main checkout path, cwd = worktree"
run 2 "$(read_in "$R" "$W/docs/BIG.md")"                        "non-excluded big file still blocked via a worktree path, cwd = main checkout"
git -C "$R" worktree remove "$W" --force >/dev/null 2>&1

echo "cross-checkout exclude, a worktree NESTED under the main checkout (item 2, round 2)"
NW="$R/.claude/worktrees/w1"
git -C "$R" worktree add -q "$NW" -b nested-wt-branch >/dev/null 2>&1
run 0 "$(read_in "$R" "$NW/docs/decisions/001-x.md")"           "excluded file in a nested worktree via its own path, cwd = main checkout"
run 0 "$(read_in "$NW" "$R/docs/decisions/001-x.md")"           "excluded file via the main checkout's path, cwd = nested worktree"
run 2 "$(read_in "$NW" "$NW/docs/BIG.md")"                      "non-excluded big file in the nested worktree, cwd = the nested worktree"
run 2 "$(read_in "$R" "$NW/docs/BIG.md")"                       "non-excluded big file in the nested worktree, cwd = main checkout"
git -C "$R" worktree remove "$NW" --force >/dev/null 2>&1

echo
[ "$FAILS" = 0 ] && echo "All doc guard tests passed." || { echo "$FAILS doc guard test(s) failed."; exit 1; }
