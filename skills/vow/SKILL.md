---
name: vow
description: Records a decision the user made as a numbered decision record in .accio/decisions/ (what was decided, the options with their pros, cons and costs, the choice and why) and commits it.
when_to_use: When the user says "record this decision", "write that down as a decision", "log the decision", or runs /accio:vow, and when wand settles a real decision, in a repo with an .accio/ folder. Not for writing design text (wand) or stories (sort).
allowed-tools: Read, Write, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-vow *)
---

# vow: record a decision

You write down one decision the user made, so a later reader knows what was chosen, from what, and why. Run the
script as its own Bash command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/accio-vow …`), with no variables or
chains. If it exits with an `accio-vow:` error, say it in plain words and stop.

1. **Gather it from the conversation.** What was decided and why it was the user's to decide; the options that were
   on the table, each with what it looks like in practice, its pros, cons and costs (each kind of cost on its own,
   never added up, with numbers and their source where you have them); the option chosen, in the user's words when
   they gave any; and why. Ask only for what is missing, one question at a time. Never record a decision the user
   hasn't made: say it is still open instead.
2. **Name it.** Run `accio-vow next "<short title>"`. It gives the path and number.
3. **Write it** at that path with the Write tool, in the format of
   `${CLAUDE_SKILL_DIR}/references/decision-format.md`: plain words, no jargon the user didn't use.
4. **Record it.** Run `accio-vow record <path>`. It checks the number and the sections, and commits the record
   alone. If it refuses, fix what it names and run it again. If its reply has `"commit": null`, the record is
   written but not committed: say why (`commit_error`).

End with one line: `Recorded decision <NNN>: <title> (<path>)`.
