# Fix brief: $story_id $title

Fix only the findings below. Nothing else changes. If a finding conflicts with the story (it asks for what the
Definition of Done rules out, or contradicts it), don't fix it: return NEEDS_CONTEXT and name the finding in your
report; accio's judge rules on it.

## Where you work
- Worktree: `$worktree` (branch `$branch`)
- Your first command: `$claim_command`
- Start every Bash command that touches files with `cd $worktree_q &&`, or use `git -C $worktree_q`.
- Commit each fix as a checkpoint.
- Write your report to `$report` again, in full, with these short sections: $report_sections (the
  review summary quotes them).

## Findings to fix
$findings
