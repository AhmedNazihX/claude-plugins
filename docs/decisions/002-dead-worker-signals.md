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

- **Transcripts:** the capstone project's folders under `~/.claude/projects/` (194 project folders: the main
  checkout and its worktrees). They hold 2,016 `.jsonl` files, of which 1,336 are subagent transcripts
  (`<session>/subagents/agent-<id>.jsonl`). 1,330 of those have an `agent-<id>.meta.json` next to them; its
  `agentType` is `foreman:story-worker` for **180**. Those 180 are "the workers" below. Dates 2026-09-28 to
  2026-10-13, Claude Code 2.1.282 to 2.1.296.
- **Method:** throwaway stdlib scripts that print only field names, enum values, counts and durations. No message
  text was printed, copied or kept. The appendix has the core of the measuring script.
- **One line, one record.** Split the file on `\n` only. Python's `str.splitlines()` also splits on characters
  like U+2028 inside a record, which broke 18 records in the worker transcripts; splitting on `\n` broke none.

## Prompts, resumes and wake-ups

R5 must know where the worker's current turn began. Three `user` record shapes carry text that is not a tool
result (counts in the 180 workers):

| Shape | Fields | Count | What it is |
| --- | --- | --- | --- |
| **Initial prompt** | `message.content` is a string; no `isMeta` | 180 (one per worker) | the launch brief |
| **Resume** | string content, `isMeta: true`, `origin.kind: "coordinator"` (178) or `"human"` (2) | 180 | `SendMessage` or the user starting a new turn |
| **Wake-up** | string content, `isMeta: true`, `origin.kind: "task-notification"` | 14, in 7 workers | a background task finished while the worker was idle |
| Injected context (not a prompt) | string content, `isMeta: true`, no `origin` | 217 | added inside a turn; the turn goes on |
| Text-block list (not a prompt) | `message.content` is a list of `text` blocks, no `tool_result` | 45 | added inside a turn; the turn goes on |

**"The last prompt"** below means the last initial prompt or resume. A wake-up does not start a new task, but it
does mean the worker is live. While the worker is busy, the same notices arrive as `attachment` records with
`attachment.type: "queued_command"` and `commandMode: "task-notification"` (130), and a `SendMessage` as one with
`origin.kind: "coordinator"` (29).

The first write after a prompt comes quickly: median 2 s, 90th percentile 15 s, longest 81 s (360 prompts).

## The record shapes

Every error notice Claude Code writes is an `assistant` record with `message.model: "<synthetic>"`,
`isApiErrorMessage: true`, `message.stop_reason: "stop_sequence"`, all `message.usage` token counts `0`, and one
`text` content block. The top-level `error` field names the kind. The text varies by version and is never matched.
Counts are records, not workers.

| Failure mode | Record shape (fields and values) | Records: all transcripts / workers |
| --- | --- | --- |
| **usage-limit** | synthetic record with `error: "rate_limit"`, `apiErrorStatus: 429` and `quotaLimits.status: "rejected"`. `quotaLimits` also has `resetsAt` (Unix seconds), `rateLimitType` (`five_hour` or `seven_day`), `overageStatus`, `isUsingOverage` and `unifiedRateLimitFallbackAvailable`. From 2.1.292 on there is also `apiError: "usage_limit_reached"` and `apiErrorParams.rate_limit_info` (the same fields). | 28 / 3 |
| **api-error** | synthetic record with any other `error`: `server_error` (no status field), `unknown`, `authentication_failed`, or `rate_limit` with `apiErrorStatus: 429`, `apiErrorIsTransient: false` and no `quotaLimits` (throttling, not the usage limit). | `server_error` 27 / 7; `unknown` 2 / 2; `authentication_failed` 1 / 0; throttling 3 / 0 |
| **context-overflow** | **Not observed.** No synthetic record is about the context. Main sessions compact instead (`type: "system"`, `subtype: "compact_boundary"`, `compactMetadata.trigger: "auto"`, 7 times); no worker has one. | 0 / 0 |
| **finished-no-report** | **No real death observed.** The closest shape: the last `assistant` record is a real turn with `stop_reason: "end_turn"` and only `text` blocks, with no `SubagentHandback` since the last prompt. | — / 1 worker, and it had handed back before its last resume |

What happened after each one in the workers:

- **usage-limit:** after each of the 3 records the worker wrote nothing until a resume 64, 105 and 144 minutes
  later. These are real deaths.
- **unknown:** both records were followed by a resume. The worker's turn had ended.
- **server_error:** all 7 were followed within the same minute by a `tool_result` with `is_error: true` and
  `toolDenialKind: "automode-unavailable"`, then more real turns. The worker went on; a `server_error` alone is not
  a death.

Shapes that are **not** failures:

- **A normal finish.** 167 of 180 workers end with a `tool_use` named `SubagentHandback` (its `input.message` is
  the report) and its `tool_result`. Of the 11 that end on `end_turn` text, 10 had handed back earlier in the same
  turn, and the 11th had handed back before its last resume.
- **Waiting on a background task.** A worker may end its turn (`end_turn` text) while a background `Bash` task
  runs, and a wake-up starts it again. 13 of the 14 wake-ups came right after an `end_turn` record, and 9 of the
  14 came before the worker's first handback. The waits were median 1.5 min, longest 20.9 min. Counting background launches
  (`toolUseResult.backgroundTaskId`, 106) against notices does not tell these waits apart: it caught only 9 of 13.
- **Retry notices.** `type: "system"`, `subtype: "api_error"`, `level: "error"` with `retryAttempt`,
  `maxRetries`, `retryInMs` and `source` (7, main sessions only). Claude Code is still retrying.
- **Silence after a tool result.** Two workers stopped after a `Bash` tool result and never wrote again, with no
  synthetic record and no handback. Only silence shows it.

## How long a live worker goes without a write

A "write" is any record with a `timestamp`. A gap that ends in a prompt (initial or resume) is time the worker
was idle by design, so it is left out. A gap that ends in a wake-up is kept: the worker was live, waiting.

| Measure (180 workers) | Value |
| --- | --- |
| Gaps between writes | 83,471 |
| Median / 90th / 99th / 99.9th percentile | 0.6 s / 6 s / 1.2 min / 4.4 min |
| Gaps over 5 / 10 / 15 / 20 / 30 min | 68 / 32 / 6 / 5 / 4 |
| Workers with a gap over 5 / 10 / 15 / 20 / 30 min | 33 / 15 / 5 / 4 / 4 |
| Longest gap per worker: median / 90th percentile | 3.4 min / 8.2 min |
| What came before the gaps over 5 min | mostly a `Bash` `tool_use` |
| `Bash` calls with `timeout: 600000` (10 min) / no timeout | 1,196 / 14,030 |

The 4 gaps over 30 minutes are one shared stall of about 146 minutes across 4 workers at once, with no synthetic
record. It is not one worker's silence. Leaving it out, the longest live silences are a 20.9-minute background
wait and a 17.3-minute pause before a handback.

## Options

| Option | What was compared or measured | Result | Source |
| --- | --- | --- | --- |
| `watch.notice_minutes` = 5 (design default) | workers with a work gap over 5 min | 33 of 180 | appendix script |
| `watch.notice_minutes` = 10 | workers with a work gap over 10 min | 15 of 180; but a 10-minute `Bash` timeout is a normal wait | appendix script |
| `watch.stuck_minutes` = 30 (design default) | workers with a work gap over 30 min | 4 of 180, all the one shared stall | appendix script |
| `watch.stuck_minutes` = 20 | workers with a work gap over 20 min | 4 of 180, at 5 moments: the shared stall, and the 20.9-minute background wait in one of the same 4 workers | appendix script; wake-up waits from the prompt-shape count |

## Decision

Keep the design's defaults: **`watch.notice_minutes` 5** and **`watch.stuck_minutes` 30**. A notice is cheap,
and 5 minutes is past the 99.9th percentile gap. At 30 minutes no single live worker in 180 was flagged; the
longest live silence (20.9 min) leaves a margin of about 1.4×. That margin is thin, so R7 should treat "stuck" as
a question for the user, not a death, and R5 must not reap on silence alone while the worker may be waiting.

**The patterns R5 matches.** Look only at the records after the last prompt. "Silence" is the time from the
last write (the last record with a timestamp, after the last prompt or not) to now. First match wins:

1. **Finished with a report:** a `tool_use` named `SubagentHandback` after the last prompt. Not dead.
2. **No turn yet:** no `assistant` record after the last prompt. Live while the silence is under
   `watch.stuck_minutes` (the longest first write seen after a prompt was 81 s); past it, mode **unknown**. A
   usage-limit record from before a resume is not after the last prompt, so it can't match rule 3: a worker
   resumed after a limit is not reaped again.
3. **usage-limit:** the last `assistant` record is synthetic, `error == "rate_limit"`, and either
   `quotaLimits.status == "rejected"` or `apiError == "usage_limit_reached"`. Dead at once. Retry advice: resume
   after `quotaLimits.resetsAt` (Unix seconds); say whether `rateLimitType` is `five_hour` or `seven_day`.
4. **api-error:** the last `assistant` record is synthetic with any other `error`, and the silence is at least
   `watch.notice_minutes`. Retry advice: resume now (`server_error`, `unknown`, throttling); for
   `authentication_failed`, ask the user to log in first.
5. **finished-no-report:** the last `assistant` record is a real turn with `stop_reason == "end_turn"`, there is no
   report file, and the silence is at least `watch.stuck_minutes`. The wait makes a background task still running
   unlikely (the longest wait seen was 20.9 min, a margin of about 1.4×). Retry advice: resume and ask for the
   report.
6. **context-overflow:** not observed, so R5 has no matcher for it. It keeps the mode name for when a real shape is
   seen; until then such a death falls to rule 7.
7. **unknown:** the silence is at least `watch.stuck_minutes` and there is no report file. When no record in the
   transcript parses, use the file's modification time as the last write. Record the last `tool_use` name, if
   any. Never a crash.
8. **Otherwise: live.** This covers a worker mid-turn, a recent error, a recent `end_turn` and a retry notice.

**Expected verdicts for the fixtures**, with the defaults (notice 5, stuck 30), no report file, and "now" set
from the fixture's last write. These are what R5's tests should check.

| Fixture | Last write | Now = last write + 1 min | Now = last write + 31 min |
| --- | --- | --- | --- |
| `usage-limit.jsonl` | 10:01:30 | usage-limit (rule 3) | usage-limit (rule 3) |
| `usage-limit-quota-only.jsonl` | 10:01:30 | usage-limit (rule 3) | usage-limit (rule 3) |
| `api-error.jsonl` | 10:01:30 | live (rule 8) | api-error (rule 4; from + 5 min on) |
| `api-error-throttled.jsonl` | 10:01:30 | live (rule 8) | api-error (rule 4; from + 5 min on) |
| `finished-no-report.jsonl` | 10:07:00 | live (rule 8) | finished-no-report (rule 5) |
| `silent-after-tool.jsonl` | 10:01:02 | live (rule 8) | unknown (rule 7) |
| `live.jsonl` | 10:01:30 | live (rule 8) | unknown (rule 7) |
| `handback.jsonl` | 10:02:01 | finished (rule 1) | finished (rule 1) |
| `api-error-recovered.jsonl` | 10:01:41 | live (rule 8) | unknown (rule 7) |
| `resumed-after-limit.jsonl` | 10:50:00 | live (rule 2) | unknown (rule 2) |
| `background-wait.jsonl` | 10:22:02 | live (rule 8) | unknown (rule 7) |
| `api-retry.jsonl` | 10:01:10 | live (rule 8) | unknown (rule 7) |
| `line-separator.jsonl` | 10:01:11 | live (rule 8) | unknown (rule 7) |

`background-wait.jsonl` cut just before its wake-up (last write 10:01:20, the `end_turn`) is live at 10:20:00,
19 minutes into the wait, and finished-no-report only from 10:31:20. In `line-separator.jsonl` the last record
holds U+2028; a reader that splits with `splitlines()` loses it and sees 10:01:10 as the last write.

A retry notice, a wake-up, injected context and attachments are all writes: they reset the silence clock. Real
model turns are the records `workers.py turn_of` already accepts (non-zero usage); synthetic records never count.

## Consequences

- **Fixtures** in `foreman/tests/fixtures/transcripts/`. Every value is made up; only field names and enum values
  match real ones. Timestamps are on 2026-01-01, so tests pass their own "now". There is no context-overflow fixture.
  - Failure shapes: `usage-limit.jsonl` (2.1.296 fields), `usage-limit-quota-only.jsonl` (2.1.290, no
    `apiError`), `api-error.jsonl` (`server_error`), `api-error-throttled.jsonl`, `finished-no-report.jsonl` (the
    shape seen: handback, resume, then a turn that ends in text), `silent-after-tool.jsonl` (unknown, by silence).
  - Near-misses, all live or finished: `live.jsonl`, `handback.jsonl`, `api-error-recovered.jsonl`,
    `resumed-after-limit.jsonl`, `background-wait.jsonl` (`end_turn`, then a task-notification wake-up),
    `api-retry.jsonl` (a retry notice is the last record), `line-separator.jsonl` (a record with U+2028 inside;
    `splitlines()` gives 8 lines for its 7 records).
- **R5:** "one test per mode" covers usage-limit, api-error, finished-no-report and unknown; context-overflow
  has no shape to test yet. Split lines on `\n`. Find "the last prompt" by the fields above.
- **R7:** the defaults stay 5 and 30. One stall can hit every worker at once, so `watch` should say when several
  workers go silent together, rather than report each as stuck.
- **Q1 / `workers.py context`:** `last_turn` splits with `splitlines()` and skips a record with U+2028 inside. It
  fails soft (it falls back to an earlier turn), but should split on `\n`.
- **Revisit when:** a Claude Code update changes these fields (`apiError` arrived in 2.1.292), a context-overflow
  or finished-without-report death is seen, or a live worker is silent past 30 minutes.

## Appendix: the measuring script

Run with Python 3 and the capstone folder path; it prints only counts. It reproduces the synthetic-record counts
for the workers and the gap table above.

```python
import glob, json, sys, collections
from datetime import datetime
root = sys.argv[1]  # ~/.claude/projects/<folder>; every folder starting with it is read
def recs(p): return [json.loads(l) for l in open(p, encoding="utf-8").read().split("\n") if l.strip()]
def ts(r): return datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) if "timestamp" in r else None
def prompt(r):  # the initial prompt, or a resume by the coordinator or a human
    c, kind = (r.get("message") or {}).get("content"), (r.get("origin") or {}).get("kind")
    return r.get("type") == "user" and isinstance(c, str) and (not r.get("isMeta") or kind in ("coordinator", "human"))
workers = [m[:-10] + ".jsonl" for m in glob.glob(root + "*/*/subagents/agent-*.meta.json")
           if json.load(open(m)).get("agentType") == "foreman:story-worker"]
synthetic, timeouts, gaps, worst = collections.Counter(), collections.Counter(), [], []
for p in workers:
    rs = recs(p)
    synthetic.update(r.get("error") for r in rs if (r.get("message") or {}).get("model") == "<synthetic>")
    timeouts.update((b.get("input") or {}).get("timeout") for r in rs if r.get("type") == "assistant"
                    for b in r["message"].get("content") or [] if b.get("type") == "tool_use" and b.get("name") == "Bash")
    timed = [r for r in rs if ts(r)]
    g = [(ts(b) - ts(a)).total_seconds() / 60 for a, b in zip(timed, timed[1:]) if not prompt(b)]
    gaps += g
    worst.append(max(g, default=0))
gaps.sort()
print("workers", len(workers), "synthetic records by error", dict(synthetic))
print("gaps", len(gaps), {q: round(gaps[int(q * len(gaps))], 2) for q in (.5, .9, .99, .999)})
for m in (5, 10, 15, 20, 30):
    print(f"> {m} min: gaps {sum(x > m for x in gaps)}, workers {sum(x > m for x in worst)}")
worst.sort()
print("longest gap per worker: median", round(worst[len(worst) // 2], 1), "p90", round(worst[int(.9 * len(worst))], 1))
print("Bash timeouts", timeouts.most_common(2))
```

It prints every row of the gap table except "what came before the gaps over 5 min". That row and the other
counts (prompt shapes, wake-ups, endings, the all-transcript totals) come from the same reading, with `Counter`s
over the fields named in each table.
