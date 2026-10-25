# Brief: $story_id $title

You implement this one story. Take your task only from this brief, and read whatever code you need.
$notes$earlier

## Context
$context

## Where you work
- Worktree: `$worktree` (branch `$branch`, starting from `$base`)
- Your first command: `$claim_command`
- Start every Bash command that touches files with `cd $worktree_q &&`, or use `git -C $worktree_q`.
- Work test-first. Tag every test with the DoD line it proves (for example `$story_id/1` in its name or a comment).
- Make small checkpoint commits as you go.
- Write your report to `$report`, with these short sections: $report_sections (the review summary quotes them).

## Definition of Done
$dod

## Files you may change (plus their tests)
$files

## Existing code to reuse
$reuse

## Checks to run
$checks

## Scripts you may run
- `accio-claim`
- `accio-board refresh`
$allowed
## Review notes
$review_notes
$answered
