# Design template

`.accio/design.md` is one page that grows by sections. `accio-board record-design` refuses it without an
`## Outcome` that has real text. `sort`'s quill reads it to write stories: keep each part concrete (who, what, which
files, how it is checked).

```markdown
# Design: <name>

## Outcome
After this ships, <what should be true>, and we'd know because <a measurable sign>.

## Who and why
<who uses it, what they do today, what hurts>

## Requirements
- <requirement> — owner: <person or role> (<why they need it>)

## Out of scope
- <what we won't do now>
- <a requirement nobody owned> (no owner)

## Design
<the chosen option in plain words: the parts, how they talk, where the data lives; the decisions by number,
e.g. "SMTP through our relay (decision 003)">

## What we build
1. **<part>.** <what it does, for whom>. Files: <paths it will add or change>. Needs: <earlier parts, or none>.
   Risk: <auth, payment, migration … or none>. Checked by: <a test, a measurement or a command that shows it works>.

## Evidence
<the chosen option's fourth depth answer: what, other than a model or the user, shows the whole thing is right.
Each part's "Checked by" comes from it.>

## Open questions
<spikes and anything left for later; "none" when nothing is open>
```

A **design note** for a later feature is one `## <Feature>` section added at the end, with the same parts as `###`
subsections, its own `### Outcome` first. Stories from a note copy that note's outcome. Never rewrite the rest.
