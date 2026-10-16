# 002 · Dead-worker signals in a transcript

- **Date:** 2026-10-16
- **Story:** X2 (docs/BACKLOG.md)
- **Status:** accepted

## Question

What does a story-worker's transcript look like when the worker has died, and how long does a live worker go
without writing to it? `workers.py reap` and `watch` (D10, stories R5 and R7) match these shapes, so they must come
from real transcripts, not guesses. See [Design › D10](../DESIGN.md#wave-2-reliability-core) and
[Design › Early experiments](../DESIGN.md#early-experiments).

## What was read

- **Transcripts:** the capstone project's folders under `~/.claude/projects/` (194 session folders, 2,016 `.jsonl`
  files, 1,336 subagent transcripts). A subagent's `agent-<id>.meta.json` names its `agentType`; **180** of them
  are `foreman:story-worker`. They span 2026-09-28 to 2026-10-13, Claude Code 2.1.282 to 2.1.296.
- **Method:** throwaway stdlib scripts (not committed) that print only field names, enum values, counts and
  timestamps. No message text was printed, copied or kept. Any number below can be re-measured the same way.
- **One line, one record.** Split the file on `\n` only. Python's `str.splitlines()` also splits on characters
  like U+2028 inside a record, which broke 18 records in the worker transcripts; splitting on `\n` broke none.
  (`workers.py last_turn` uses `splitlines()` today; it fails soft, but see Consequences.)

## The record shapes

Every error notice Claude Code writes is an `assistant` record with `message.model: "<synthetic>"`,
`isApiErrorMessage: true`, `message.stop_reason: "stop_sequence"`, all `message.usage` token counts `0`, and one
`text` content block. The top-level `error` field names the kind. The text varies by version and is never matched.

| Failure mode | Record shape (fields and values) | Seen (all transcripts / story-workers) |
| --- | --- | --- |
| **usage-limit** | synthetic record with `error: "rate_limit"`, `apiErrorStatus: 429`, and `quotaLimits.status: "rejected"`. `quotaLimits` also has `resetsAt` (Unix seconds), `rateLimitType` (`five_hour` or `seven_day`), `overageStatus`, `isUsingOverage`, `unifiedRateLimitFallbackAvailable`. From 2.1.292 on it also has `apiError: "usage_limit_reached"` and `apiErrorParams.rate_limit_info` (the same fields). | 28 records / 3 records in 3 workers |
| **api-error** | synthetic record with any other `error`: `server_error` (no status field), `unknown`, `authentication_failed`, or `rate_limit` with `apiErrorStatus: 429`, `apiErrorIsTransient: false` and no `quotaLimits` (throttling, not the usage limit). | `server_error` 27 / 7; `unknown` 2 / 2; `authentication_failed` 1 / 0; throttling `rate_limit` 3 / 0 |
| **context-overflow** | **Not observed.** No synthetic record in any transcript is about the context. Main sessions compact instead (`type: "system"`, `subtype: "compact_boundary"`, `compactMetadata.trigger: "auto"`, 7 times); no story-worker transcript has one. | 0 / 0 |
| **finished-no-report** | the last `assistant` record is a real model turn (`model` not `<synthetic>`) with `stop_reason: "end_turn"` and only `text` blocks, and no `tool_use` named `SubagentHandback` since the last prompt. | — / 11 workers, all in a turn after a resume, all with a handback in an earlier turn |

Related shapes that are **not** failures:

- **A normal finish.** 167 of 180 workers end with an `assistant` `tool_use` named `SubagentHandback` (its
  `input.message` is the report) and then a `user` `tool_result` record. So "last record is a tool result" is
  normal at the end, and the handback is the sign of a report.
- **A recovered error.** All 7 `server_error` records in worker transcripts were followed within the same minute
  by a `user` `tool_result` (with a `toolDenialKind` field) and more real turns. A `server_error` alone is not a
  death; only one with no write after it is.
- **Retry notices.** `type: "system"`, `subtype: "api_error"`, `level: "error"` with `retryAttempt`,
  `maxRetries` and `retryInMs` (7, main sessions only). Claude Code is still retrying.
- **Two workers stopped after a `Bash` tool result** and never wrote again, with no synthetic record and no
  handback. Nothing in the transcript says why; only silence shows it.

What a death looks like over time: after each of the 3 usage-limit records in worker transcripts, the next record
was a new prompt (the orchestrator resuming the worker) 64, 105 and 144 minutes later. The worker wrote nothing in
between. The same holds for the 2 `unknown` errors (the next record was a new prompt).

## How long a live worker goes without a write

A "write" is any record with a `timestamp`. A gap ending in a new prompt is a resume, not work, and is left out.

| Measure (180 worker transcripts) | Value | Source |
| --- | --- | --- |
| Gaps between writes during work | 83,188 | survey |
| Median / 90th / 99th / 99.9th percentile gap | 0.6 s / 6 s / 1.1 min / 4.2 min | survey |
| Gaps over 2 / 5 / 10 / 15 / 30 min | 459 / 64 / 29 / 5 / 4 | survey |
| Longest gap per worker: median / 90th percentile | 3.4 min / 6.8 min | survey |
| Workers with a gap over 5 / 10 / 15 / 30 min | 32 / 14 / 5 / 4 | survey |
| What came before the 64 gaps over 5 min | a `Bash` `tool_use` in 45, an attachment record in 17, a tool result in 2 | survey |
| `Bash` calls with `timeout: 600000` (10 min) / no timeout | 1,196 / 14,029 | survey |

The 4 gaps over 30 minutes (146–147 min) all started within 2 minutes of each other (2026-10-10 06:04–06:06 UTC)
in 4 different workers, with no synthetic record. Everything stalled at once (the machine asleep, most likely),
so they are not one worker's silence. Without them, the longest work gap seen is 17 minutes.

## Options

| Option | What was compared | Result | Source |
| --- | --- | --- | --- |
| `watch.notice_minutes` = 5 (design default) | workers with a gap over 5 min | 32 of 180 get a notice | survey above |
| `watch.notice_minutes` = 10 | workers with a gap over 10 min | 14 of 180; but a 10-minute `Bash` timeout is a normal wait | survey above |
| `watch.stuck_minutes` = 30 (design default) | workers with a gap over 30 min | 4, all one shared stall; 0 from a single worker | survey above |
| `watch.stuck_minutes` = 15 | workers with a gap over 15 min | 5: the shared stall plus one 17-minute gap | survey above |

## Decision

Keep the design's defaults: **`watch.notice_minutes` 5** and **`watch.stuck_minutes` 30**. A notice is cheap
and 5 minutes is past the 99.9th percentile gap. At 30 minutes no single worker in 180 was silent while alive, and
30 leaves three times the longest normal wait (a 10-minute `Bash` call).

**The patterns R5 matches**, read from the end of the transcript, first match wins:

1. **Finished with a report:** a `tool_use` named `SubagentHandback` after the last prompt. Not dead; leave it.
2. **usage-limit:** the last `assistant` record is synthetic, `error == "rate_limit"`, and either
   `quotaLimits.status == "rejected"` or `apiError == "usage_limit_reached"`. Dead at once. Retry advice: resume
   after `quotaLimits.resetsAt` (Unix seconds); say whether `rateLimitType` is `five_hour` or `seven_day`.
3. **api-error:** the last `assistant` record is synthetic with any other `error`, and nothing was written after
   it for `watch.notice_minutes`. Retry advice: resume now (`server_error`, `unknown`, throttling); for
   `authentication_failed`, ask the user to log in first.
4. **finished-no-report:** the last `assistant` record is a real turn with `stop_reason == "end_turn"`, no
   pending `tool_use`, no `SubagentHandback` since the last prompt, and no report file. Retry advice: resume and ask
   for the report.
5. **context-overflow:** not observed, so R5 has no matcher for it. It keeps the mode name for when a real shape is
   seen; until then such a death falls to the next rule.
6. **unknown:** no write for `watch.stuck_minutes` and no report file; or a record that doesn't parse as any of
   the above. Record the last `tool_use` name. Never a crash.

Real model turns are the records `workers.py turn_of` already accepts (non-zero usage); synthetic records have
all-zero usage, so they never count as a turn.

## Consequences

- **Fixtures:** `foreman/tests/fixtures/transcripts/` holds one synthetic file per shape: `usage-limit.jsonl`
  (2.1.292+ fields), `usage-limit-quota-only.jsonl` (older, no `apiError`), `api-error.jsonl` (`server_error`),
  `api-error-throttled.jsonl` (`rate_limit` without `quotaLimits`), `finished-no-report.jsonl`,
  `silent-after-tool.jsonl` (unknown, by silence), and the near-misses `live.jsonl`, `handback.jsonl` and
  `api-error-recovered.jsonl`. Every value in them is made up; only field names and enum values match. Their
  timestamps are on 2026-01-01, so tests pass their own "now". There is no context-overflow fixture.
- **R5:** "one test per mode" covers usage-limit, api-error, finished-no-report and unknown; context-overflow
  has no shape to test yet. Split lines on `\n`, not `splitlines()`.
- **R7:** the defaults stay 5 and 30. One stall can hit every worker at once (the 146-minute pause), so `watch`
  should say when several workers go silent together, rather than report each as stuck.
- **Q1 / `workers.py context`:** `last_turn` splits with `splitlines()` and skips a record that contains U+2028.
  It fails soft (it falls back to an earlier turn), but should split on `\n`.
- **Revisit when:** a Claude Code update changes these fields (the `apiError` field arrived in 2.1.292), a
  context-overflow death is seen, or a real run shows a live worker silent past 30 minutes.
