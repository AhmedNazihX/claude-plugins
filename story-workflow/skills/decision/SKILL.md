---
name: decision
description: Writes a decision record in docs/decisions/NNN-<slug>.md — what was decided, the options compared, the numbers with their sources, and the choice. Use whenever a story or the design phase makes a choice (a model, a library, a threshold, a licence reading, a stack layer), when a review asks the user to decide a trade-off, or when the user says to record, log or document a decision.
argument-hint: "<short title>"
---

# Record a decision: $ARGUMENTS

1. **Number it.** List the existing records and take the next free three-digit number. The config may reserve
   numbers for specific stories (`.claude/story-workflow.json` › `decisions.reserved`, for example
   `{"003": "X1 model choice"}`). If this decision belongs to a reserved story, use its number.
   **In a story worktree** (parallel workers could pick the same number), use the reserved number if there is one;
   otherwise name the file `docs/decisions/NNN-<slug>.md` with the letters `NNN`, and `story-finish` gives it the
   next free number when it merges the story.
   ```bash
   ls docs/decisions/ 2>/dev/null
   jq -r '.decisions.reserved // {} | to_entries[] | "\(.key) \(.value)"' .claude/story-workflow.json 2>/dev/null
   ```
2. **Gather the facts** from the conversation, the story's output files and any stored run records. Every number
   needs a source (a file, a run id, a command, a doc URL). Never estimate or round a number the user will quote.
   When two measurements of the same thing differ, record the one the committed code produces and say why.
3. **Write** `docs/decisions/NNN-<kebab-slug>.md`:

```markdown
# NNN · <Title>

- **Date:** YYYY-MM-DD
- **Story:** <ID> (docs/BACKLOG.md), or "design" for a kickoff decision
- **Status:** accepted | superseded by NNN | proposed (waiting for the user)

## Question
One or two sentences: what had to be decided and why it matters. Link the section of docs/DESIGN.md.

## Options
| Option | What was compared or measured | Result | Source |
| --- | --- | --- | --- |
| … | … | … | run id / file / command / doc URL |

## Decision
The choice, in one sentence, and the rule that decided it (for example the design's "switch if >10% broken").

## Consequences
- What changes: settings, defaults, which stories are affected.
- What would make us revisit it.
```

4. **Apply** a setting the decision changes only if the story's DoD asks for it; otherwise list it under
   Consequences.
5. If the decision needs the user's judgement (a licence reading, a label, a trade-off no rule settles), set the
   status to `proposed`, ask the user one question with your recommendation, and mark it `accepted` only after
   they answer. Record the date and what they chose.
6. **Hand over:** add a short note that points to the record on each backlog story it affects.
