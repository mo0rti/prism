# Incident report - Blank review summary for right-to-left comments

Reported by support on 2026-10-09.

## What happened
Reviewers who exported the summary of a review whose comments contain right-to-left text (Arabic or Hebrew) received a PDF with a blank page. The first report came in at 09:10, about forty minutes after release REL-002 of the review summary export reached production.

## Impact
Every export of a review with right-to-left comment text returned a blank page. Exports of reviews without such text were not affected. Eleven reviewers reported it in the first hour.

## Timeline
- 09:10: Support received the first report of a blank summary.
- 09:25: Support confirmed that only reviews with right-to-left comment text are affected.
- 09:40: The on-call engineer was paged.

## Cause
Not known yet. The blank page appeared only after REL-002.

## What has been done
Nothing yet stops the harm. Reviewers were told to send their comments on by hand until it is fixed.
