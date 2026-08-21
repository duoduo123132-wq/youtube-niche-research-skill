# Evidence contract

## Top-level document

Use schema version `1.0` and preserve this shape:

```text
schema_version
run
statuses
evidence
failures
topics (optional, agent-authored)
```

`run` records the research name, search phrases, target language, lookback,
retrieval time, collection status, quota ledger, and candidate counts by query.
Never add an API key, authorization header, or access token.

## Statuses

Keep these decisions independent:

- `coverage_status`: whether the qualified sample has enough breadth.
- `performance_status`: whether age-adjusted strong signals were found in that
  sample; use `not_evaluable` when coverage is insufficient.
- `audience_status`: whether enough cleaned public comments support recurring
  needs; do not infer absence of demand from disabled or unavailable comments.

Preserve the associated qualified, coverage, channel, strong-signal,
audience-video, and cleaned-comment counts.

## Evidence items

Require a unique stable `evidence_id` and retain at least:

- source video and channel IDs, title, publication time, duration, and views;
- search provenance and metadata-language match;
- channel baseline count, median context, raw multiple, age, velocity, and
  age-adjusted multiple;
- qualification and strong-signal flags;
- public, fetched, and cleaned comment counts plus the comment collection state;
- public subscriber context when available.

Normalized comments may contain only comment ID, text, like count, publication
time, and reply count. Exclude commenter identity and reply bodies.

Every topic must reference one or more evidence IDs from the current document.
Reject unknown, missing, or cross-run references.
