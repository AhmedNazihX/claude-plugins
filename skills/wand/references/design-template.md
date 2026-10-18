# Design template

`.accio/design.md` is one page that grows by sections. `accio-board record-design` refuses it without
`## Outcome`. `sort`'s quill reads it to write stories: keep each part concrete (who, what, which files).

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

## Design
<the chosen option in plain words: the parts, how they talk, where the data lives; the decisions by number,
e.g. "Postgres (decision 003)">

## What we build
1. **<part>.** <what it does, for whom>. Files: <paths it will add or change>.

## Evidence
<wandmaker's fourth depth answer: what, other than a model or the user, shows it is right (a test, a measurement, a
check a tool runs). This seeds the stories' DoD lines.>

## Open questions
<anything left to a spike or to later; "none" when nothing is open>
```

A **design note** for a later feature is one `## <Feature>` section with the same parts as subsections (`###`),
added at the end. Never rewrite the rest of the file.
