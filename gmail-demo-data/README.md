# Gmail CRE demo data

The Toolhouse Worker seeds `properties.csv` into an empty `Properties` worksheet by calling the demo MCP's `get_seed_properties` tool. The live CLI parses `email-templates.md` and sends the ten messages from `aadityasoni2020@gmail.com` to `aaditya@toolhouse.ai`; no `.eml` export or fake inbox import is involved. See [`docs/gmail-demo-runbook.md`](../docs/gmail-demo-runbook.md).

This directory contains only synthetic demo inputs:

- [`properties.csv`](properties.csv): import as the `Properties` worksheet; exactly 30 rows.
- [`processed-emails.csv`](processed-emails.csv): import as the empty `ProcessedEmails` worksheet.
- [`email-templates.md`](email-templates.md): ten messages to send as real Gmail messages from a secondary account.

The Google Sheet is the only database in the demo path. Do not convert these messages into mailbox-export files.

See the complete setup in [`docs/gmail-demo-runbook.md`](../docs/gmail-demo-runbook.md).
