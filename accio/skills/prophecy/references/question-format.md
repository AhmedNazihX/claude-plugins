# How prophecy asks a question

Every question that is the user's to decide is written so they can answer without asking back, in this order:

1. **What is being decided, in plain words**, and why it is theirs to decide. Say what a term means the first time.
2. **A concrete example** of what each option looks like in practice: what changes, what they would see.
3. **For each option: pros, cons and the cost or saving** (time, money, risk, quality), with numbers where you have
   them. Say plainly when an option's benefit is small. Keep each kind of cost on its own line; never add them up.
4. **Your recommendation and why**, then **one question**. Stop and wait for the answer.

A short table works well for the options. Ask one question per message, never a numbered list of questions.

## Example: a story whose dependency was dropped

> **S-014 "Rate-limit the reset form" depends on S-012 "Password reset email", which was dropped** ("we use the
> identity provider's reset page instead"). Without S-012 there is no reset form to limit, so S-014 can't be built
> as written. This is yours: it decides whether the work is still wanted.
>
> | Option | What happens | Pros | Cons |
> |---|---|---|---|
> | Drop S-014 too | it leaves the backlog, with the reason "its dependency S-012 was dropped" | the backlog stays honest | none, if the form is truly gone |
> | Remove the dependency | S-014 can be planned now and is built against what exists | keeps the work | its DoD talks about a form that won't exist; it likely needs rewriting first |
>
> **My recommendation:** drop it too, because the form it protects won't exist.
> **Drop S-014 too, or keep it and remove the dependency?**

## Example: bundled low-stakes defaults

> Three small choices have an obvious default, so I'll take these unless you say otherwise:
> - S-021's error message is in English only (the rest of the app is).
> - S-022 keeps the existing 30-minute session timeout.
> - S-023 stays on the Quick track (2 files, no risky path).
>
> **Are these three fine?**
