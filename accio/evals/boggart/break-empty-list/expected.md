Planted break: an empty list crashes.
Claim: "0.0 when it is empty" (S-902/2, and the docstring at stats.py:2)
Repro: `average([])` should be `0.0`; it raises `ZeroDivisionError`. The story's test for the empty case passes
`[0]`, which is not empty.
