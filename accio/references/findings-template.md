# Findings: <story ID> · <reviewer>

One item per finding, most severe first. A finding counts only with confidence ≥ 80. Leave the list empty when
nothing reaches that bar, and say so in one line.

```
- id: <reviewer>-<n>             (examiner-1, professor-2 …; a re-review keeps the ids of the first round)
  status: open | resolved        (resolved only in a re-review, for a finding the fix answered)
  severity: critical | major | minor
  confidence: <0-100>
  where: <file:line>, or <file> or "story" for something missing (a check, a test, a guard)
  claim: <one plain sentence: what is wrong>
  failure: <a concrete input or state, and the wrong result it gives>
  dod: <the DoD tag it concerns, e.g. S-012/2, or "none">
```

- **critical:** the story would ship broken, lose data, or open a security hole an outsider can use.
- **major:** a DoD line isn't met; a test passes for the wrong reason; or a concrete input gives a wrong result, a
  crash, or access it shouldn't, without being critical.
- **minor:** worth fixing, but the story works without it.
