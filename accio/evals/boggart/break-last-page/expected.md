Planted break: the last partial page is dropped.
Claim: "The last page holds the remainder." (S-901/2, and the docstring in pager.py:2)
Repro: `paginate(list(range(7)), 3, 3)` should be `[6]`; the code returns `[]` because `pages = len(items) // size`
rounds down. The story's own test only uses a full last page, so it never saw this.
