# Gmail RAG Pivot Council Review

The architecture was pressure-tested through five independent roles: Contrarian, First Principles, Expansionist, Outsider, and Executor. Their proposals were compared without using author identity as a ranking signal; the role names below identify the perspective, not seniority.

## Where the Council Agrees

- This should be an additive pivot around the existing evidence spine, not a rewrite.
- The useful product is `email -> structured temporal knowledge -> match -> grounded draft`, not generic inbox chat.
- PostgreSQL remains canonical. Qdrant is a scoped, rebuildable retrieval index; Google Sheets is at most an export.
- Gmail messages must be segmented before extraction. The current whole-body heuristic is a live-data stop-ship because it converts legal-footer addresses into properties.
- Requirements, properties, physical spaces, listings, claims, and workflow state are distinct concepts.
- Facts are append-only claims with exact source spans, authority, modality, and time. Current views are projections.
- Unknown must remain unknown in requirement matching.
- One consented test mailbox plus ten deliberately created test messages is the starting scope; captured payloads are sanitized for deterministic replay.
- Mailbox/account access filters must apply before SQL, vector, Toolhouse, drafting, and citation work.
- Email content cannot authorize actions. Draft creation, sending, follow-ups, and VTS mutations require separate capability and human-approval gates.
- The first proof should be a temporal, held-out vertical slice so the system cannot retrieve the human answer it is supposed to predict.

## Where the Council Clashes

### Contrarian

The Contrarian would pause live Gmail work until the data-retention and Google-policy interpretation is signed off. A persistent cross-user inbox database can create more legal and security risk than product value. This view prefers bounded retention or on-demand retrieval, one mailbox, no raw message persistence where avoidable, and no agent access to Gmail credentials.

Peer review accepted the stop-ship policy gate and bounded-retention fallback. It rejected waiting to do any engineering: create deliberate test messages, then use sanitized captured payloads for repeatable segmentation, extraction, matching, and deletion tests.

### First Principles

The First Principles view reframes the system around three invariants:

1. a mailbox is a stream of observations, not truth;
2. a factual answer is a projection over temporal claims;
3. an external action is a separately authorized state transition.

This view favors a claim ledger and explicit space/configuration model immediately, even if it costs more than extending `PropertyRecord`.

Peer review agreed with the invariants but recommended a staged schema. Keep `PropertyRecord` as a compatibility projection while the claim ledger becomes authoritative; do not block the first vertical slice on a perfect enterprise ontology.

### Expansionist

The Expansionist sees the larger opportunity:

- proactive requirement detection;
- portfolio-wide match alerts;
- “what changed?” timelines;
- response drafting in broker style;
- stale availability detection;
- VTS and follow-up automation;
- relationship intelligence across brokers, tenants, properties, and requirements.

This view would add graph infrastructure, live Gmail, Toolhouse, external brochure crawling, and VTS early to maximize the demo.

Peer review retained the product opportunities but rejected making them one critical path. Relational edges are enough initially; broad crawling and mutations follow only after the evidence, access, and approval gates pass.

### Outsider

The Outsider’s concern is user trust and workflow fit. Brokers do not want another database to maintain, but they also will not adopt a system that drafts plausible emails from stale or mixed evidence. The most convincing interface is not a chat box; it is a requirement card, an explained shortlist, a draft, and a compact evidence receipt.

This view favors Gmail-native review and keeps the legacy application outside the pivot path.

Peer review concluded that Gmail drafts should be the pilot review surface. The legacy application can remain as a regression reference, but it must not participate in or shape the Gmail product path.

### Executor

The Executor optimizes for demonstrable progress:

1. create ten real test messages and capture sanitized payloads;
2. encode the existing pasted-sample footer false-positive as a failing regression;
3. build `SourceEnvelope` and segment roles;
4. extract one requirement and one listing response;
5. match and render a draft;
6. only then connect one mailbox.

This view would initially use a scheduler over Gmail history because it is simpler than Pub/Sub.

Peer review accepted the offline sequence and a scheduler as a development trigger, but not whole-inbox polling. The sync service must always be cursor-driven. Production should use Gmail watch plus Pub/Sub and periodic reconciliation because notifications are lossy signals, not a durable event log.

The real disagreements therefore resolve as:

| Decision | Resolution |
| --- | --- |
| Rewrite versus evolve | Evolve additively |
| Flat records versus full ontology | Claim ledger now; normalized entities incrementally; `PropertyRecord` as projection |
| Live Gmail first versus offline proof | Toolhouse Worker + Gmail-tool wiring demo, then deterministic captured-payload regression tests |
| Polling versus Pub/Sub | Shared cursor-driven service; scheduler for development, Pub/Sub for deployment |
| Permanent shared index versus bounded scope | One mailbox and bounded retention until explicit policy/legal approval |
| Review surface | Use editable Gmail drafts; keep the legacy UI outside the pivot path |
| VTS now versus later | Capability spike and dry-run outbox after draft quality; writes last |
| Graph database now versus later | PostgreSQL relations first; add only after measured need |

## Blind Spots the Council Caught

- Google’s approved CRM/productivity use case does not automatically authorize indefinite database copies or cross-user exposure.
- `gmail.metadata` is still Restricted and cannot support body/attachment RAG.
- A Gmail notification contains a mailbox and history signal, not the changed message.
- An `INBOX`-only watch misses sent and archived material; the sample outgoing responses contain the best supply knowledge.
- Push delivery can be duplicated, delayed, reordered, or dropped. Cursor handling and reconciliation are the reliability mechanism.
- The current worker only starts under Slack configuration, so a Gmail-only deployment would enqueue nothing unless startup is decoupled.
- Current SQL and vector retrieval are not principal-scoped; filtering after generation is too late.
- Re-import currently deletes/recreates child rows, which can weaken stable replay and evidence links.
- A forwarded wrapper date can incorrectly make an old fact look fresh.
- Provider AI summaries can be wrong and must never become factual evidence.
- “Same information above” has ambiguous scope and cannot be copied blindly.
- NNN, amps, KVA, parking ratios, and `$/SF/year` require distinct unit semantics.
- Contiguous area may be added when supported; amperage usually may not.
- Style retrieval can leak stale facts unless it is physically/logically separated from the fact lane.
- A held-out answer must not appear in the retrieval corpus used to generate the evaluated draft.
- Citation-ID allowlisting does not prove that each sentence is entailed by the cited span.
- Email and attachments are prompt-injection surfaces and can never grant action authority.
- Public VTS documentation does not establish that this customer has the write endpoint needed to create/update the desired record.
- Google verification/security assessment and VTS access can dominate elapsed calendar time even when engineering is finished.

## The Recommendation

Adopt a three-horizon plan.

Horizon 1 — prove the product with deliberate test mail:

- ten real messages sent into a `CRE-DEMO` Gmail label;
- Toolhouse scheduled Worker → Gmail tool → CRE MCP wiring proof;
- sanitized captured payloads for deterministic replay;
- provider-neutral source and access contracts;
- MIME and nested-forward segmentation;
- requirement/listing/correction extraction;
- temporal claims;
- deterministic matching;
- grounded draft with exact evidence;
- no external writes.

Horizon 2 — prove one safe mailbox:

- `gmail.readonly`;
- bounded backfill and cursor-based incremental sync;
- durable checkpoints;
- deletion/revocation;
- mailbox-scoped SQL, Qdrant, Toolhouse, and citations;
- security/policy sign-off.

Horizon 3 — add actions:

- Gmail draft creation through incremental authorization;
- approved follow-up tasks;
- VTS capability discovery, dry-run, sandbox, and application-deduplicated approved mutation only after endpoint retry semantics are confirmed;
- broader team sharing only after explicit grants and isolation testing.

Keep the existing Slack implementation only as a regression harness. Do not connect it to the Gmail demo path, rebuild its UI, or delete it during the first pivot sprint.

The leading success metric is not answer fluency. It is zero unsupported factual claims, zero cross-account leakage, correct temporal status, and a useful draft that a broker can approve with minimal editing.

## The One Thing to Do First

Create ten real test messages, capture sanitized payloads from them, and turn the current pasted-sample footer-address extraction failure into a release-blocking test.

That single move converts the pivot from architecture prose into an executable contract. The first passing vertical slice must extract the 10K–30K Austin lab requirement and `Project Alpha` evidence while producing zero property records from the two sanitized legal-footer addresses. Everything else—Gmail OAuth, Qdrant, Toolhouse, VTS, and polished UI—should wait behind that proof.
