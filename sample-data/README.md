# Sample Data

This directory contains the local fixtures for the evidence-spine import path.

The authoritative loader input is [import-manifest.json](import-manifest.json), which maps Slack-shaped metadata to local fixtures under `files/`.

The fixture set now includes native PDF and XLSX files alongside CSV and text notes. The importer parses those native files locally, preserves page/sheet/row metadata on chunks, and still uses the manifest's seeded property records for deterministic demo answers.

The dataset is aligned with [docs/sample-data-and-evaluation.md](../docs/sample-data-and-evaluation.md).

