# Method checklists (decision 011)

The story's `risk` field picks the checklists the reviewers apply, on top of their usual review. Each one lists what
an expert in that area would run or inspect. They are methods, not voices: do what the expert does, don't write
like one.

| `risk` holds the word | Checklist |
|---|---|
| `auth`, `security`, `secret`, `permission`, `payment` | `auth-and-security.md` |
| `performance`, `perf`, `latency`, `scale` | `performance.md` |
| `migration`, `schema`, `data` | `data-migration.md` |
| `accessibility`, `a11y`, `ui` | `accessibility.md` |

Words are matched whole (split at spaces, commas and dashes), so `author` is not `auth` and `build` is not `ui`.
A story with no `risk` gets no checklist. A diff that touches a risky path (`risky_paths` in config.json) also gets
`auth-and-security.md`, whatever its `risk` field: `auror` joins the review then and always applies it.
