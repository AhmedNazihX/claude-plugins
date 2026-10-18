# Review package: $story_id $title

$scope

## Where
- Worktree: `$worktree` (branch `$branch`); reviewed commit `$head`
- The diff: `$diff` ($shortstat). Read it in parts if it is long.
- The story: `$story_file`; the implementer's report: `$report`
- The project's checks and accio's scripted checks passed; don't run them again.

## Your findings
Write them to `$findings` (your name in place of `<reviewer>`), in the format of `$template`. That is the only file
you may write.

## Definition of Done
$dod

## Files the story may change (plus their tests)
$files

## Risky paths it touches
$risky_files

## Method checklists
Checklists: $checklists
