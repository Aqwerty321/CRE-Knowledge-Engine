# Sample Data

This directory contains the local fixtures for the evidence-spine import path.

The authoritative hand-authored loader input is [import-manifest.json](import-manifest.json), which maps Slack-shaped metadata to local fixtures under `files/`. Generated manifest fragments under [generated](generated) are merged automatically by the importer.

The fixture set now includes native PDF and XLSX files alongside CSV and text notes. The importer parses those native files locally, preserves page/sheet/row metadata on chunks, and still uses the manifest's seeded property records for deterministic demo answers.

The current corpus has 27 Slack-shaped sources and 2,425 seeded property rows: 23 hand-authored demo sources with 25 property rows plus four generated global CRE CSV shards with 2,400 property rows. The generated shards cover US and European markets, richer property types, locality/neighborhood fields, status, usage, facing, furnishing, infrastructure, coordinates, map links, and `additional_information` remarks.

Regenerate the large corpus deterministically with:

```bash
uv run cre-cli build-large-corpus --rows 2400 --seed 20260519
```

The generator writes [generated/import-manifest-large-corpus.json](generated/import-manifest-large-corpus.json), [generated/large-corpus-quality-report.json](generated/large-corpus-quality-report.json), and four Slack-seedable CSV shards under [files](files). The generated records are synthetic commercial profiles over geospatial-style public locality metadata; `source_metadata_json` tags them as deterministic demo enrichment.

The high-signal expanded queries are:

- `List all properties.`
- `Show me the cheapest properties.`
- `What do we know about 18 Beacon Freight?`
- `Show industrial listings available soon under $35/SF.`
- `What is the average rent for industrial listings under $35/SF?`
- `Find whse opts with trk court and trlr parking.`
- `Which options look best for a logistics tenant under $35/SF available soon?`

The dataset is aligned with [docs/sample-data-and-evaluation.md](../docs/sample-data-and-evaluation.md).

## Planned Gmail Pivot Fixtures

The current fixture set remains the regression baseline for the working Slack application. Gmail-pivot fixtures should be added as a separate, sanitized corpus; do not commit the supplied raw customer emails, names, addresses, signatures, tracking links, or OAuth data.

The first demo email corpus should be created as ten real messages sent from a secondary Gmail account into a `CRE-DEMO` label. For deterministic extractor tests, commit only sanitized text/JSON payloads captured from those test messages—not private mailbox exports. The corpus should include:

- prior listing and availability emails as the searchable supply history;
- a later, held-out tenant requirement that is not accompanied by the human-written answer;
- nested forwards and replies with distinct original, forwarded, received, and processed times;
- HTML-only marketing mail, inline images, and representative PDF/XLSX attachments;
- signatures, legal disclaimers, unsubscribe content, tracking links, and provider AI summaries;
- corrections, conditional statements, ambiguous suite aliases, and changing availability;
- a deletion/tombstone case and an access-scope isolation case;
- adversarial instructions in message or attachment content to verify that evidence cannot authorize actions.

The release-blocking regression is the supplied sample's current failure mode: the new pipeline must extract the real requirement and the property represented by sanitized alias `Project Alpha` while producing zero property records for either sanitized legal-footer address. Evaluation fixtures must keep source history earlier than the held-out requirement so response retrieval cannot leak the answer being scored.

See the [Gmail RAG pivot roadmap](../docs/gmail-rag-pivot-roadmap.md) for the fixture contract, expected CRE claims, and phase gates.
