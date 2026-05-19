# Sample Data

This directory contains the local fixtures for the evidence-spine import path.

The authoritative loader input is [import-manifest.json](import-manifest.json), which maps Slack-shaped metadata to local fixtures under `files/`.

The fixture set now includes native PDF and XLSX files alongside CSV and text notes. The importer parses those native files locally, preserves page/sheet/row metadata on chunks, and still uses the manifest's seeded property records for deterministic demo answers.

The current corpus has 23 Slack-shaped sources and 25 seeded property rows. The newer additions make the demo less toy-sized: a last-mile industrial watchlist, client tour notes, a tenant expansion brief, retail/office follow-ups, access-constraint notes, and fresh Slack messages around 18 Beacon Freight, 42 Spruce Flex, and 510 River Cold Storage.

The high-signal expanded queries are:

- `List all properties.`
- `Show me the cheapest properties.`
- `What do we know about 18 Beacon Freight?`
- `Show industrial listings available soon under $35/SF.`
- `What is the average rent for industrial listings under $35/SF?`
- `Find whse opts with trk court and trlr parking.`
- `Which options look best for a logistics tenant under $35/SF available soon?`

The dataset is aligned with [docs/sample-data-and-evaluation.md](../docs/sample-data-and-evaluation.md).

