# Report contract

## Required sections

Use all eight headings defined by `validate.py`, covering research parameters,
scope, the three statuses, strongest evidence, sub-directions, audience needs,
candidate topics, and limitations/next steps.

## Evidence citations

Cite evidence with `[evidence-id]`, for example `[yt-v1]`. Every factual insight,
sub-direction, audience claim, and candidate topic must point to one or more IDs
from the current run. Do not cite an ID from another run.

## Language and excerpts

Give every English title or quoted English term a Chinese explanation on the same
line. Keep public-comment excerpts short, omit commenter identity, and link users
to the source video instead of reproducing long comment text.

## Claims

Describe only the configured sample. Prefer wording such as “本次样本发现强播放信号”
or “当前样本不足”. Never declare that an entire niche is viable, impossible, or
guaranteed to succeed.

Generate `report.md` and `evidence.json` by default. Generate `topics.csv` only
when the user requests it, with the exact columns enforced by `validate.py`.
