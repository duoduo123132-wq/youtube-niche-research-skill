# YouTube Niche Research Skill Design

Date: 2026-08-20

## 1. Objective

Create a standalone Codex Skill that lets a user research a YouTube niche from an
agent conversation. The user supplies their own YouTube Data API key. The Skill
collects public evidence locally, applies deterministic quality checks, asks Codex
to derive evidence-linked insights, and exports a bilingual Markdown report plus
a normalized evidence JSON file. A topics CSV is generated only when requested.

The Skill reports signals found within the configured search sample. It does not
claim to discover the whole YouTube market, prove that a niche will succeed, or
prove that no opportunity exists outside the collected sample.

This is not a website and does not depend on the existing YouTubeWorkbench
application.

## 2. Product Boundary

### Included in version 1

- Install and invoke the Skill from Codex or another compatible agent.
- Accept a research name, one to five search phrases, target language, video
  duration range, and publication lookback window.
- Help the user obtain and configure their own YouTube Data API key through
  official Google links.
- Use only read-only YouTube Data API methods.
- Estimate API request usage before a live scan and ask before consuming quota.
- Search videos, batch-fetch video/channel metadata, and load recent channel
  uploads for a channel baseline.
- Read up to 100 public top-level comments per selected evidence video.
- Cache reusable responses locally in SQLite.
- Calculate channel baselines, raw and age-adjusted outlier multiples, and evidence
  eligibility.
- Clean comments with domain-neutral rules.
- Ask Codex to identify sub-directions, audience needs, objections, and candidate
  topics only from persisted evidence.
- Export normalized evidence JSON and a bilingual Markdown report by default.
- Export a topics CSV only when the user requests a spreadsheet-friendly artifact.
- Report sample coverage, performance signals, and audience-demand evidence as
  separate statuses instead of fabricating a binary niche verdict.
- Run on Windows, macOS, and Linux with Python 3.11 or newer.

### Excluded from version 1

- Web UI, server deployment, registration, payment, teams, or multi-user storage.
- PostgreSQL, Redis, queues, workers, or the Hong Kong deployment gate.
- OAuth access to a user's YouTube channel.
- Publishing, commenting, liking, subscribing, deleting, or changing YouTube data.
- Unofficial scraping, yt-dlp, proxies, API-key rotation, or quota circumvention.
- Transcripts, thumbnail downloading, video downloading, and script imitation.
- A separate Ollama, OpenAI API, or other AI-provider dependency.
- Importing the old YouTubeWorkbench database or its domain-specific fallback
  templates.

## 3. Recommended Approach

Build a clean, self-contained Skill instead of copying the old application.
Reuse only validated formulas and data-contract ideas. Do not import production
modules from YouTubeWorkbench.

Rejected alternatives:

1. Copy existing modules: faster initially, but it imports web/database coupling
   and known cross-niche fallback contamination.
2. Wrap the full application: feature-rich, but heavy to install and contrary to
   the agent-first product decision.

## 4. Repository Layout

```text
youtube-niche-research-skill/
├── README.md
├── LICENSE
├── .gitignore
├── skills/
│   └── youtube-niche-research/
│       ├── SKILL.md
│       ├── agents/
│       │   └── openai.yaml
│       ├── scripts/
│       │   ├── collect.py
│       │   ├── analyze.py
│       │   └── validate.py
│       └── references/
│           ├── youtube-api-setup.md
│           ├── evidence-contract.md
│           └── report-contract.md
├── tests/
│   ├── fixtures/
│   └── test_*.py
└── docs/superpowers/
    ├── specs/
    └── plans/
```

The GitHub-facing README and license stay outside the Skill folder. The installed
Skill contains only agent instructions, required scripts, and on-demand reference
material.

## 5. User Experience

Example request:

> Research the YouTube niche "AI for beginners" in English, using videos between
> 8 and 20 minutes. Explain all English results in Chinese.

The Skill performs this sequence:

1. Validate Python and the API-key configuration.
2. If the key is missing, show Chinese instructions and official Google links.
3. Validate input and warn about overly broad one-word queries. If the user gives
   only a broad niche name, propose three to five specific search phrases and get
   approval before consuming quota.
4. Display the planned search calls, baseline calls, comment calls, and upper
   request bound.
5. Ask the user to confirm the live read-only scan.
6. Collect and cache raw public responses.
7. Normalize and score evidence deterministically.
8. Ask Codex to derive semantic findings from the normalized evidence.
9. Validate every claim/topic against its evidence references.
10. Write artifacts to a new run directory and summarize the result in chat.

No browser or persistent local service is opened.

## 6. Configuration and Secret Handling

- Read `YOUTUBE_API_KEY` from the process environment.
- Optionally load it from a workspace-local `.env` that is excluded by
  `.gitignore`.
- Never print, serialize, export, commit, or include the key in an exception.
- Redact query parameters before recording request diagnostics.
- Provide these official setup links:
  - `https://console.cloud.google.com/apis/library/youtube.googleapis.com`
  - `https://console.cloud.google.com/apis/credentials`
- Recommend an API restriction to YouTube Data API v3.
- Do not request OAuth channel authorization because version 1 reads public data
  only.

## 7. Data Collection

### Search

- Accept one to five specific search phrases.
- Accept a 12-month, 24-month, 36-month, or all-time publication window; default
  to the most recent 24 months.
- Use at most one result page per phrase by default.
- Request videos only and collect no more than 25 results per phrase.
- De-duplicate video IDs across phrases while preserving every matching phrase as
  search provenance.
- Record candidate counts by phrase and channel so the report exposes sampling
  concentration.
- Batch video and channel detail calls where the API permits up to 50 IDs.
- Record every raw response with endpoint, non-secret parameters, retrieval time,
  and a content hash.

### Channel baseline

- Resolve the channel uploads playlist without `search.list`.
- Load up to 30 recent public uploads.
- Batch-fetch their video details.
- Apply the configured publication window and duration range, and exclude
  upcoming/live content.
- Require at least 10 eligible baseline videos.
- Use the median eligible view count as the baseline.
- Compute and store `candidate views / channel median views` as the raw outlier
  multiple.
- Compute `age_days = max(retrieved_at - published_at, 1 day)` and
  `view_velocity = views / age_days` for the candidate and every baseline video.
- Use the median eligible baseline view velocity and compute
  `candidate view velocity / channel median view velocity` as the age-adjusted
  outlier multiple.
- Use the age-adjusted multiple for strong-signal classification. Keep the raw
  multiple as context rather than the decisive metric.

### Comments

- Fetch up to 100 public top-level comments per selected evidence video.
- Request plain text and order by relevance by default.
- Store comment ID, text, like count, published time, and reply count.
- Do not require or expose commenter identity in reports.
- Do not fetch every reply in version 1; record total reply count for later work.
- Treat `commentsDisabled`, unavailable comments, and quota exhaustion as explicit
  collection states, never as empty audience demand.

## 8. Local Persistence

Each workspace gets a local data directory excluded from source control:

```text
.youtube-niche-research/
├── cache.sqlite3
└── runs/
    └── YYYYMMDD-HHMMSS-slug/
        ├── evidence.json
        ├── report.md
        └── topics.csv  # optional, generated only when requested
```

SQLite caches successful read-only API responses using a canonical request key and
retrieval timestamp. Raw API responses remain in this local cache for audit and
re-analysis; they are not a default user-facing export. Default freshness:

- video/channel details: 24 hours;
- channel baselines: 24 hours;
- comments: 12 hours;
- completed run outputs are immutable and never overwritten.

## 9. Evidence and Acceptance Rules

### Qualified performance sample

A video enters the qualified performance sample when:

- its publication date is inside the configured lookback window;
- its target-language match is acceptable;
- its duration is within the requested range;
- it is not upcoming or live; and
- its channel baseline contains at least 10 eligible videos.

Comments are not required for performance qualification. Disabled or sparse
comments must not erase valid playback evidence.

### Strong performance signal

A qualified video is a strong performance signal when its age-adjusted outlier
multiple is at least 3. Store the raw outlier multiple, publication age, view
velocity, channel subscriber count when public, and view-to-subscriber ratio as
secondary context.

Keep every qualified video in the evidence file, but count no more than three
videos from one channel toward project-level coverage. This prevents a single
channel from dominating the sample without discarding its records.

### Audience-demand evidence

A qualified video has audience-demand evidence when:

- its public comment count is at least 50;
- at least 50 public top-level comments were fetched successfully; and
- comment cleaning leaves enough non-spam material for analysis.

Audience-demand evidence is evaluated independently from performance evidence.
A video may carry a strong performance signal without usable comments, or useful
audience-demand evidence without being a strong outlier.

### Project-level statuses

Report three independent statuses:

- `coverage_status`: `insufficient` until at least 30 qualified videos across at
  least 8 channels remain after the per-channel coverage cap; otherwise
  `sufficient`;
- `performance_status`: `not_evaluable` while coverage is insufficient;
  `strong_signals_found` when at least 5 qualified videos are strong signals;
  otherwise `no_strong_signal_in_sample`;
- `audience_status`: `not_evaluable` until at least 5 qualified videos and at
  least 250 cleaned comments provide audience-demand evidence;
  `recurring_needs_found` when repeated needs are evidence-linked; otherwise
  `no_recurring_need_in_sample`.

Do not collapse these statuses into “the niche is viable” or “the niche is not
viable.” Use sample-bounded language such as “strong signals were found in this
sample,” “the sample is insufficient,” or “no strong signal was found in this
sample.”

Every insight and candidate topic references one or more evidence IDs. A topic
without an evidence link is rejected.

## 10. Domain-Neutral Comment Analysis

Deterministic preprocessing:

- normalize Unicode and whitespace;
- remove URLs, contact handles, repeated promotional text, and obvious spam;
- filter global stop words;
- extract meaningful two-to-four-word phrases;
- retain question, audience, scenario, tool, constraint, complaint, and desired
  outcome phrases;
- keep representative comments separately from aggregate terms.

Codex semantic analysis receives the current run's title, description, normalized
phrases, and representative comments only. It does not receive topics from prior
runs and has no food, finance, AI, health, or other domain fallback templates.

If semantic evidence is weak, write `insufficient evidence` instead of filling a
generic template.

## 11. Report Contract

`report.md` is mandatory. Codex writes its findings in this file while following
the evidence and language rules below. The Skill owns the contract and validation;
the agent owns the evidence-grounded analysis and wording.

`evidence.json` is mandatory and is produced deterministically by the collection
scripts. It contains normalized source records, collection states, computed
metrics, and stable evidence IDs. The agent must never invent or rewrite evidence
records.

`topics.csv` is optional. Generate it only when the user requests CSV or a
spreadsheet-friendly topic list. The serialization and evidence-link validation
remain deterministic even though topic wording comes from the agent.

`report.md` contains:

1. research parameters and collection status;
2. search phrases, publication window, and sampling limitations;
3. coverage, performance, and audience statuses with missing conditions;
4. qualified sample, strong-signal, audience-evidence, and distinct-channel
   counts;
5. strongest evidence table, including publication age and age-adjusted metrics;
6. automatically discovered sub-directions;
7. audience needs and objections with comment evidence;
8. candidate topics with evidence IDs;
9. limitations, failures, concentration, and quota notes;
10. next research action.

English titles and quoted terms include Chinese explanations. Reports use short
excerpts only and link to the original YouTube video. Raw comments remain local and
are not copied into the GitHub repository.

## 12. Failure Handling

- Missing key: stop before network access and show setup instructions.
- Invalid/restricted key: stop with a redacted actionable error.
- Quota exhausted or rate-limited: preserve completed artifacts and report the
  checkpoint; do not reinterpret this as a negative niche verdict.
- Comments disabled: keep video evidence but mark comment evidence unavailable.
- Partial API failure: do not overwrite prior cache; report exact failed stage.
- No qualified evidence: export an honest insufficient-sample report and no final
  topics CSV.
- Cross-niche or unlinked topic: reject it in the validation step.

The collector never performs write-capable YouTube API methods.

## 13. Verification Strategy

### Skill behavior tests

Before authoring `SKILL.md`, record baseline agent failures using synthetic
research requests. Re-run the same cases with the Skill and verify that the agent:

- checks for a key and quota estimate before live collection;
- does not fabricate conclusions from insufficient evidence;
- does not introduce domain-specific fallback topics;
- preserves Chinese explanations for English output;
- does not expose secrets or imply channel OAuth is required.

### Script tests

Use fixture-only tests with no live API access to prove:

- request batching and quota estimates;
- API-key redaction;
- cache identity and freshness;
- publication-window, duration, language, and live filters;
- raw and age-adjusted baseline/outlier calculation;
- cross-query de-duplication and per-channel coverage caps;
- comments-disabled and partial-result states;
- domain-neutral phrase extraction;
- evidence-linked topic validation;
- independent coverage, performance, and audience statuses;
- deterministic evidence JSON and optional CSV serialization;
- stable Markdown structure with evidence-linked agent analysis.

One explicitly authorized manual smoke test may use the developer's own API key
after all offline tests pass. The test must consume a small, displayed request
budget and must not persist the key.

## 14. GitHub Distribution

- Use a dedicated repository named `youtube-niche-research-skill`.
- Use the MIT license unless the user later chooses a different license.
- Include installation and example usage in the repository README.
- Include no API keys, `.env`, caches, outputs, raw comments, old databases, server
  addresses, or YouTubeWorkbench history.
- Validate the Skill folder with the official Skill validation helper before
  publishing.
- Creating the remote repository, committing, and pushing require separate
  explicit confirmation under the user's account-change rules.

## 15. Acceptance Criteria

Version 1 is ready to share when:

1. a clean-machine install is documented and repeatable;
2. a user can configure their own YouTube API key without exposing it;
3. one agent request produces `evidence.json` and bilingual `report.md`, and can
   produce `topics.csv` on request;
4. all offline tests pass without network access;
5. insufficient samples, API failures, and sample-limited negative results cannot
   become whole-market conclusions;
6. every report insight/topic is traceable to current-run evidence;
7. cross-domain fixture tests show no template contamination;
8. the Skill validator passes;
9. a secret scan finds no credentials or private data;
10. the GitHub publish scope is reviewed and explicitly approved.
