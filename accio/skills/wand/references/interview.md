# How wand interviews

One question per message. Each question is written so the user can answer without asking back:

1. **What is being decided, in plain words**, and why it is theirs to decide. Say what a term means the first time.
2. **A concrete example** of what each answer looks like in practice.
3. **For each option: pros, cons, and the cost or saving**, each kind on its own line, with numbers and their
   source when you have them (from seeker's notes, never from memory). Say plainly when a benefit is small.
4. **Your recommendation and why**, then **one question**. Wait for the answer.

Short questions are fine for facts ("Who uses this: your team, or customers?").

## What to find out
- **The outcome**, always, in these words: "After this ships, what should be true, and how would you know?" The
  answer goes into the design's Outcome section, and quill copies it into every story.
- **Who it is for** and what they do today.
- **Each requirement and its owner**: the person or role who needs it, and why. A requirement nobody owns is
  deleted: "Nobody needs X, so I've taken it out." Owners can be the user ("me, for the weekly report").
- **What must not change** (existing behaviour, data, integrations) and the limits (budget, deadline, hosting).
- **What is out of scope**, said out loud, so the stories don't grow.
- **A clash with a recorded decision.** Read the titles of `.accio/decisions/*.md`, and the whole of any that bear
  on the idea. When the new design or note contradicts one, say which decision (its number and title) and what
  each side says, then ask: replace the decision (record a new one with vow, its text saying "Replaces decision
  NNN"), or change the note so it keeps the decision. Example: decision 004 says "data stays on our server", and
  the note sends invoices to a hosted service.

Stop when a builder would no longer have to guess; don't ask what the code or seeker can answer.
