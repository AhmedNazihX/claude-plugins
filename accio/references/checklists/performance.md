# Performance

- Find every loop over data that can grow (rows, files, requests). What does it cost at 10x and 100x today's size?
- Look for a query or a network call inside a loop (N+1), and for missing limits or pagination.
- Check new indexes or caches match the queries that use them, and that a cache has an expiry and a size bound.
- Look for work done on every request that could be done once (parsing, compiling, reading config).
- If the DoD names a time or size target, find the test or benchmark that measures it, and check it measures the
  right thing (warm vs cold, realistic data).
