# Evidence-linked shared knowledge for agent swarms

Status: design agreed in conversation on 2026-10-29. This document describes a proposed system, not implemented or validated behavior.

## Purpose and first use

Provide agents doing software implementation and review with task-relevant project documents, code references, decisions, prior agent findings and test evidence. The first experiment includes both source material and agent-produced knowledge, with evidence and interpretation distinguishable. The corpus is non-sensitive by assumption; sensitive-content classification and hosted-model data restrictions are outside this scope.

## Architecture

A standalone local catalog holds source records, addressable sections, and agent-produced records. Original sources remain authoritative and are not replaced by generated summaries. Many-to-many topic indexes are navigational views linking to records, not copies of the content. Each agent has a versioned role definition; role-specific usefulness annotations adjust retrieval ranking and evidence mix, but do not exclude material solely because its role score is low. Current task relevance remains primary.

An orchestrator or agent requests a task-specific slice using a task, role and budget. Candidate search operates over section content, topic links and agent records. Typed decision models can assess bounded relevance judgments and indicate uncertainty or the need to broaden search. Returned records identify their source anchors, lifecycle status and supporting evidence. An unsupported agent claim is labeled as such; an evidence link establishes traceability, not truth.

## Records and metadata

Common metadata: stable identity and type; origin and creation time; source revision or content digest; lifecycle status and supersession links; and precise retrieval anchor. Types include source, section, agent finding, decision and test result. Agent records include producer, evidence links and evidence status; test results reference actual recorded output where available. Topics record their assignment method and review state. Role annotations record role and role version, estimated usefulness, scoring method, model/version when applicable, and source revision. Initial model-generated scores are hypotheses, not measured utility or calibrated probabilities.

Source revisions and generated records remain distinguishable. A changed source makes dependent links and annotations stale for rechecking; preserve prior versions and relationships. Quarantined or provisional proposals must remain identifiable; a model judgment alone is not independent verification. The catalog uses a single logical owner for writes in the first slice; multi-process concurrent writing is not assumed safe.

## Ingestion and indexing

Extract text and anchors; retain existing ToC or headings when usable. If missing, propose a source-linked structural index from available text and layout; label generated boundaries and retain page or text anchors. If extraction or structure is weak, retain whatever source text is usable for broader search and mark the deficiency; report an explicit failure when no searchable text can be extracted. Do not assume PDF embedded bookmarks are a complete printed ToC.

Generate candidate topics and links to sections or agent records. A bounded decision can classify a proposed link as supported, unclear or unsuitable. Record method, inputs or references, model version, outcome and status. Unclear or failed judgments remain provisional, rather than silently accepted or discarded. Source updates invalidate or flag dependent annotations for reassessment.

## Retrieval and failure handling

Search candidate records by text and topic, then optionally assess relevance with a typed decision model and adjust ordering using role annotations. Return anchors, evidence links, status and the reason for any broadening or fallback. An uncertain decision can trigger a broader search; timeout, malformed response, unavailable provider or missing role score results in an explicit unknown and a broader or ungated search, never silent evidence suppression. Role scores do not confer authority or guarantee utility.

Decision calls are behind a provider-neutral interface. JevEdge0's local typed scoring and option-order stability are candidates for evaluation; its conditional option scores are not calibrated confidence. Hosted OpenRouter Decisions models are alternatives, not chosen winners; compare model IDs, actual provider availability, latency, cost, option limits and task performance before selection. A model may rank or classify, but deterministic software owns record validation, provenance, versioning and fallback.

## Prior work and boundaries

STAIR provides ideas for hierarchical section addressing and demonstrates that a valid title is not necessarily relevant; its current PDF corpus builder yields no sections without embedded ToC entries. JevEdge0 offers local typed decisions, hybrid search and stability checks, with reported limitations on calibration. HITMCockpit supplies role-oriented orchestration and proposed shared-mind lifecycle concepts; its existing store and swarm integration must be verified before reuse. None of these establishes a measured improvement for this system. Integration is an adapter boundary, not a change to those repositories in the first experiment.

## Evaluation

Use real implementation and review tasks with independently identified relevant evidence, including missing ToCs, broad topics, stale sources, conflicting claims, unsupported findings and role differences. Compare on the same corpus and tasks: (1) ordinary section/text search, (2) topic-aware search, (3) topic-aware plus decision judgments, and (4) decision judgments plus role ranking. Use held-out cases for threshold and role-score evaluation; explicitly report unanswerable or missing-source cases.

Measure evidence recall and relevance, unsupported or stale material returned, indexing and query costs, latency and context size. Log actual model/provider versions, calls, failures, tokens and costs where available. If agents perform tasks, independently review their outcomes; retrieval metrics, model scores and agent self-reports do not establish task success. Record no improvement claim unless the comparison supports it.

## Deferred choices

Production swarm integration, multi-writer coordination, a broad knowledge graph, automatic learned role scores, provider selection, live hosted inference and a general-purpose document platform are deferred. The initial implementation plan chooses a minimal local technology for a reproducible research slice, not a permanent architecture commitment.
