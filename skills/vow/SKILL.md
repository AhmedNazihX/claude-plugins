---
name: vow
description: Records a decision the user made as a numbered decision record in .accio/decisions/ (what was decided, the options with their pros, cons and costs, the choice and why) and commits it.
when_to_use: When the user says "record this decision", "write that down as a decision", "log the decision", "write an ADR" or "decision record", or runs /accio:vow, and when wand settles a real decision, in a repo with an .accio/ folder. Not when the user also wants a design written (wand records those decisions itself), nor for stories (sort).
allowed-tools: Read, Write, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-vow *)
---

# vow: record a decision

You write down one decision the user made, so a later reader knows what was chosen, from what, and why. Run the
script as its own Bash command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/accio-vow …`), with no variables or
chains. One decision per run: name, write and record it before the next.

1. **Is it made?** A decision is made when the user picked an option or plainly accepted a recommendation ("go with
   yours" counts: Status then says `decided by the user (accepted the recommendation)`). If options were only
   discussed, or only you recommended one, it is open: say so, ask the one question that settles it, and record
   nothing until they answer.
2. **Gather it from this conversation only.** What was decided and why it was the user's to decide; the options,
   each with what it looks like in practice, its pros and cons, and its costs or savings; the choice, in the user's
   words when they gave any; and why. Never add a figure, price or fact from your own knowledge or other files.
   Ask only when the choice, the options or the reason is missing; for anything else not discussed, write
   `not discussed`.
3. **Name it.** Run `accio-vow next '<short title>'` (single quotes; an apostrophe inside becomes `’`). If it exits
   with an `accio-vow:` error (a build is running, for one), say it in plain words and stop.
4. **Write it** at that path with the Write tool, in the format of
   `${CLAUDE_SKILL_DIR}/references/decision-format.md`: plain words, explaining a term the first time.
5. **Record it.** Run `accio-vow record <path>`. It checks the number and the sections, and commits the record
   alone. If it refuses, fix what it names and run it once more; if it refuses again, show its message and stop.

End with one line: `Recorded decision <NNN>: <title> (<path>)`, or, when its reply has `"commit": null`,
`Wrote decision <NNN> but did not commit it: <commit_error>`.
