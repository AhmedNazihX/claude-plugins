# Drops heredoc bodies from a shell command, so hooks match commands and not file content.
# Used by the guard hooks: awk -f lib/strip-heredocs.awk
# - Keeps the opener line (for example `cat > path <<EOF`), so a heredoc writing to a guarded path is still seen.
# - Skips here-strings (`<<<`): they have no body.
# - For `<<-`, compares the terminator after stripping leading tabs, as the shell does.
inh {
  line = $0
  if (dash) sub(/^\t+/, "", line)
  if (line == term) inh = 0
  next
}
{ print }
match($0, /(^|[^<])<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/) {
  op = substr($0, RSTART, RLENGTH)
  sub(/^[^<]/, "", op)                 # drop the character before <<
  dash = (substr(op, 3, 1) == "-")
  term = op
  gsub(/^<<-?[ \t]*|["\047]/, "", term)
  inh = 1
}
