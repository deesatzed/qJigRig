# Independent labeling packet: five draft tasks

Purpose: identify which source sections a software agent would need for each task. This is a request for independent relevance judgments, not a test of the reviewer. Do not use retrieval rankings or generated model judgments when labeling.

Corpus: [shared-knowledge design](plans/2026-10-29-shared-knowledge-design.md) and [implementation plan](plans/2026-10-29-shared-knowledge-implementation.md), at the source revisions recorded by the eventual run. Only these two files are in this preliminary corpus. The earlier smoke run did not provide any relevance labels.

For each task, list the headings that provide evidence needed to carry it out. More than one heading may be relevant. If information is missing from both files, describe what is missing; do not assume a heading contains the answer because of its title. Distinguish source text that must be read from merely related context. Leave a task unreviewed if you have not inspected the whole corpus for it.

| ID | Role | Task | Relevant headings and file | Missing information / notes |
| --- | --- | --- | --- | --- |
| implement-fallback | Implementer | Implement a source-linked fallback when a document has no headings. | | |
| review-evidence | Reviewer | Check how an agent finding identifies its supporting source. | | |
| implement-timeout | Implementer | Handle a decision-model timeout without suppressing source evidence. | | |
| review-role | Reviewer | Assess whether role usefulness may hide an otherwise relevant section. | | |
| review-calibration | Reviewer | Determine whether provider scores have been validated as task accuracy. | | |

Record reviewer identity, review date, and source revisions with completed labels. The packet's five tasks are exploratory and insufficient by themselves for a reliable model comparison or threshold calibration. Prior draft suggestions in `docs/evaluation.md` were prepared by the implementer and are not independent labels.
