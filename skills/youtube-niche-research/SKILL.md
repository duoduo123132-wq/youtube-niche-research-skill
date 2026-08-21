---
name: youtube-niche-research
description: Use when researching YouTube niches or competitor evidence, comparing outlier videos, interpreting public comments and audience needs, or producing bilingual evidence-backed reports.
---

# YouTube Niche Research

## Overview

Research only the configured YouTube sample. Separate sample coverage, playback
signals, and audience-demand evidence; never turn them into a universal niche
verdict.

## Workflow

1. Collect the research name, target language, duration range, lookback window,
   and one to five search phrases.
2. If the user gives only a broad term, propose three to five specific phrases
   with adjacent Chinese explanations and obtain their choice before collection.
3. If `YOUTUBE_API_KEY` is missing, read
   `references/youtube-api-setup.md` and provide the official setup links.
4. Run `scripts/collect.py estimate --queries N` before every live collection.
5. Display the upper-bound units and obtain explicit confirmation.
6. After confirmation, run only `scripts/collect.py run` with
   `--confirm-read-only-scan`; never use login, OAuth, scraping, or write methods.
7. Read only the new run's `evidence.json`. Do not reuse another run's topics,
   phrases, or conclusions.
8. Write bilingual `report.md` using `references/report-contract.md` and cite
   current evidence IDs. Use `references/evidence-contract.md` for field meaning.
9. Run `scripts/validate.py RUN_DIRECTORY`; correct every error before delivery.
10. Generate `topics.csv` only when the user requests CSV or spreadsheet output.

## Hard rules

- Treat API failure as collection failure, never as a negative niche finding.
- Treat disabled or sparse comments as missing audience evidence, never as missing playback evidence.
- Never say a niche is proven viable or impossible; describe only the configured sample.
- Never invent evidence, evidence IDs, comments, metrics, or topics without current-run evidence links.
- Never reuse domain templates or findings from another run.
- Never expose the API key or request channel OAuth.

## Quick reference

| Situation | Required action |
|---|---|
| Broad request | Propose 3-5 precise queries with Chinese explanations |
| Before live scan | Show quota upper bound and ask for confirmation |
| Small sample | State missing coverage conditions; do not validate the niche |
| Comments disabled | Keep playback evidence; mark audience evidence unavailable |
| Candidate topic | Attach one or more current-run `[yt-*]` evidence IDs |
| English title or term | Add Chinese explanation on the same line |
| Missing key | Use official API-key setup; never request channel login |

## Complete example

User: "Research AI for beginners" (AI 新手入门)

1. Clarify target language, 8-20 minute duration, and 24-month lookback.
2. Propose: `AI for beginners` (AI 新手入门), `ChatGPT for beginners`
   (ChatGPT 新手教程), `AI at work for non-technical people`
   (职场 AI 入门).
3. Estimate three queries and show the upper bound: 499 units.
4. Ask: "Confirm a read-only scan using at most 499 units."
5. Only after confirmation, collect into a new immutable run directory.
6. Read that run's `evidence.json`, write `report.md` with citations such as
   `[yt-v1]`, then validate both files. Do not create `topics.csv` unless asked.

## Common mistakes

| Observed failure | Required behavior |
|---|---|
| Declares a broad niche viable in a rushed answer | Refine queries, estimate quota, confirm, then report only sample-bounded statuses |
| Uses a successful prior food project to generate AI topics | Ignore prior-domain templates; use only current-run evidence |
| Gives English search terms without Chinese explanations | Pair every English title, term, query, and recommendation with Chinese |
| Refuses secret exposure but omits setup links or suggests OAuth | Provide official API-key links and redacted debugging; never request login/OAuth |

## Red flags &#8212; stop and correct the workflow

- Live request before quota display and confirmation
- Whole-market conclusion from a search sample
- Comment failure treated as playback failure
- Topic without current-run evidence IDs
- Topic or wording copied from another run
- API key, OAuth token, or channel-login request in output
