#!/bin/bash
# PreToolUse hook: keeps secrets out of the transcript, out of files and out of commits.
# Blocks by exiting 2 with a message on stderr. Heredoc bodies in shell commands are ignored (they are content,
# not commands); their opener line (`cat > .env <<EOF`) is still checked.

HERE="$(cd "$(dirname "$0")" && pwd)"
if ! command -v jq >/dev/null 2>&1; then
  echo "BLOCKED: git-guardrails needs jq to read tool calls (brew install jq). Until then, file and shell tools are blocked." >&2
  exit 2
fi

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Files that hold secrets. Templates (.env.example, .env.sample, .env.template) are allowed.
SECRET_FILE_RE='(^|/)(\.env(\.[A-Za-z0-9_-]+)?|[^/]+\.(pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa)|credentials\.json|service-account[^/]*\.json)$'
TEMPLATE_FILE_RE='(^|/)\.env\.(example|sample|template)$'
# A glob that would select a secrets file (Grep's glob, a grep --include).
SECRET_GLOB_RE='(^|/)\.env|\.(pem|key|p12|pfx)\b|id_(rsa|ed25519|ecdsa)|credentials\.json|service-account'

# Values that look like real keys. Minimum lengths keep placeholders like "sk-or-v1-xxx" allowed.
SECRET_VALUE_RE='sk-or-v1-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{32,}|sb_secret_[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|lsv2_(pt|sk)_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

block() {
  echo "BLOCKED: $1 The user has prevented you from doing this. Ask the user to handle secrets themselves." >&2
  exit 2
}

is_secret_file() {
  echo "$1" | grep -qE "$SECRET_FILE_RE" && ! echo "$1" | grep -qE "$TEMPLATE_FILE_RE"
}

has_secret_value() {
  grep -qE -- "$SECRET_VALUE_RE"
}

case "$TOOL" in
  Read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    is_secret_file "$FILE" && block "reading '$FILE' would put secrets into the transcript."
    ;;

  Grep)
    GPATH=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
    GLOB=$(echo "$INPUT" | jq -r '.tool_input.glob // empty')
    is_secret_file "$GPATH" && block "searching '$GPATH' would put secrets into the transcript."
    if [ -n "$GLOB" ] && echo "$GLOB" | grep -qE "$SECRET_GLOB_RE" && ! echo "$GLOB" | grep -qE '\.env\.(example|sample|template)'; then
      block "the glob '$GLOB' selects secrets files."
    fi
    ;;

  Write|Edit|MultiEdit|NotebookEdit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
    is_secret_file "$FILE" && block "'$FILE' is a secrets file; the user edits it by hand."
    echo "$INPUT" | jq -r '[.tool_input.content, .tool_input.new_string, .tool_input.new_source, (.tool_input.edits // [] | .[].new_string)] | map(select(. != null)) | .[]' \
      | has_secret_value && block "the content for '$FILE' contains what looks like a real API key or private key. Use a placeholder and read the value from the environment."
    ;;

  Bash)
    RAW=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    CMD=$(printf '%s\n' "$RAW" | awk -f "$HERE/lib/strip-heredocs.awk")

    # Mentions a secrets file (by path token)?
    SECRET_TOKENS=$(echo "$CMD" | tr ' \t;&|()<>"'"'"'' '\n' | grep -E "$SECRET_FILE_RE" | grep -vE "$TEMPLATE_FILE_RE")
    if [ -n "$SECRET_TOKENS" ]; then
      # Reading it in any way that prints its contents.
      if echo "$CMD" | grep -qE '(^|[^A-Za-z0-9_-])(cat|less|more|head|tail|grep|egrep|fgrep|rg|sed|awk|bat|xxd|od|hexdump|strings|base64|diff|jq|yq|source|python3?|node|ruby|perl)([^A-Za-z0-9_-]|$)|(^|[;&|[:space:]])\.[[:space:]]|<[[:space:]]*[^[:space:]]*\.env'; then
        block "'$RAW' would print a secrets file into the transcript."
      fi
      # Staging it.
      if echo "$CMD" | grep -qE 'git[[:space:]]+add'; then
        block "'$RAW' would stage a secrets file for commit."
      fi
    fi

    # The search checks read the command with quotes and backslashes removed, so a
    # disguised command word ("grep", \grep, gr''ep) is still seen as grep.
    SCMD=$(printf '%s\n' "$CMD" | tr -d "\"'\\\\")
    # grep and its kin (GNU ggrep, compressed zgrep/bzgrep/xzgrep, egrep/fgrep).
    GREP_WORD='(^|[^A-Za-z0-9_-])(g|z|bz|xz|zstd|lz)?[ef]?grep'
    # Where a command word starts: the line's start or after ; & | ( or a backtick, past any
    # sudo/command/exec/nice/time/xargs prefix. Keeps a word that is only an argument
    # (a search pattern such as `grep -c rgrep notes.md`) from counting as the command.
    CMD_POS='(^|[;&|(`])[[:space:]]*((sudo|command|exec|nice|time|xargs)([[:space:]]+-[^[:space:]]+)*[[:space:]]+)*'
    # A recursive grep reads .env too (unlike rg, which skips hidden and gitignored files by default);
    # rgrep is recursive without a flag.
    if { echo "$SCMD" | grep -qE "$GREP_WORD[[:space:]]([^;&|]*[[:space:]])?(-[A-Za-z]*[rR][A-Za-z]*|--recursive|--dereference-recursive)([[:space:]]|\$)" \
         || echo "$SCMD" | grep -qE "$CMD_POS"'rgrep([[:space:]]|$)'; } \
      && ! echo "$CMD" | grep -qE -- "--exclude(=|[[:space:]]+)['\"]?[^[:space:]]*env" \
      && ! { echo "$CMD" | grep -qE -- "--include(=|[[:space:]]+)" && ! echo "$CMD" | grep -qE -- "--include(=|[[:space:]]+)['\"]?[^[:space:]]*env"; }; then
      block "'$RAW' searches recursively and would read .env files. Add --exclude='.env*' (or use rg, which skips them)."
    fi
    if echo "$SCMD" | grep -qE '(^|[^A-Za-z0-9_-])rg[[:space:]]([^;&|]*[[:space:]])?(-[A-Za-z]*u[A-Za-z]*|--hidden|--no-ignore[A-Za-z-]*)([[:space:]]|$)' \
      && ! echo "$CMD" | grep -qE -- "(-g|--glob)[[:space:]]+['\"]?!"; then
      block "'$RAW' searches hidden or ignored files and would read .env files. Add -g '!.env*'."
    fi

    # find hands every file it lists, .env included, to a reader (| xargs grep, -exec cat).
    # Safe when it is limited by name, path or regex to something that is not env, or
    # excludes env by name.
    READER='(grep|egrep|fgrep|cat|head|tail|less|more|strings|xxd|od|sed|awk)'
    if echo "$SCMD" | grep -qE '(^|[^A-Za-z0-9_-])find[[:space:]]' \
      && echo "$SCMD" | grep -qE "(xargs([[:space:]]+-[^[:space:]]+)*[[:space:]]+$READER|-exec(dir)?[[:space:]]+$READER)([[:space:]]|\$)" \
      && ! echo "$SCMD" | grep -qE '(!|-not)[[:space:]]+-i?(name|path)[[:space:]]+[^[:space:]]*env' \
      && ! { echo "$SCMD" | grep -qE -- '-i?(name|path|regex)[[:space:]]+' \
             && ! echo "$SCMD" | grep -qE -- '(^|[[:space:]])-i?(name|path|regex)[[:space:]]+[^[:space:]]*env'; }; then
      block "'$RAW' hands every file find lists, .env included, to a reader. Add ! -name '.env*' to the find (or use rg)."
    fi

    # Printing the environment (exported keys live there).
    while IFS= read -r part; do
      read -ra W <<<"$part"
      j=0
      while [ $j -lt ${#W[@]} ] && [[ "${W[$j]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do j=$((j + 1)); done
      first=${W[$j]}
      rest=("${W[@]:$((j + 1))}")
      case "$first" in
        printenv)
          if [ ${#rest[@]} -eq 0 ] || printf '%s\n' "${rest[@]}" | grep -qiE 'key|token|secret|pass|cred|auth'; then
            block "'$RAW' would print environment variables that may hold keys."
          fi ;;
        env)
          # `env` alone (or with only options/assignments) prints everything; `env X=1 cmd` runs cmd.
          only_opts=1
          for w in "${rest[@]}"; do [[ "$w" =~ ^(-|[A-Za-z_][A-Za-z0-9_]*=) ]] || only_opts=0; done
          [ $only_opts = 1 ] && block "'$RAW' would print the whole environment, keys included." ;;
        export|declare|typeset)
          [[ " ${rest[*]} " =~ \ -p\  || ( "$first" != export && " ${rest[*]} " =~ \ -x\  ) ]] && block "'$RAW' would print exported variables, keys included." ;;
      esac
    done <<<"$(printf '%s\n' "$CMD" | sed -E 's/(\&\&|\|\||;|\|)/\n/g')"

    # Committing: scan what is about to be committed, in the repo the command commits to.
    if echo "$CMD" | grep -qE 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit'; then
      DIR=${CWD:-.}
      GC=$(echo "$CMD" | sed -nE 's/.*git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+commit.*/\1/p' | tr -d "\"'")
      if [ -n "$GC" ]; then
        case "$GC" in /*|~*) DIR=${GC/#\~/$HOME} ;; *) DIR="$DIR/$GC" ;; esac
      fi
      if echo "$CMD" | grep -qE 'commit[^;&|]*[[:space:]](-a|--all|-[A-Za-z]*a[A-Za-z]*)([[:space:]]|$)'; then
        DIFF=$(git -C "$DIR" diff HEAD 2>/dev/null)
      else
        DIFF=$(git -C "$DIR" diff --cached 2>/dev/null)
      fi
      echo "$DIFF" | grep -E '^\+' | has_secret_value && block "the changes being committed contain what looks like a real API key or private key. Unstage it and move the value to .env."
      git -C "$DIR" diff --cached --name-only 2>/dev/null | while read -r f; do
        is_secret_file "$f" && exit 3
      done
      [ $? -eq 3 ] && block "a secrets file is staged for commit. Unstage it and add it to .gitignore."
    fi
    ;;
esac

exit 0
