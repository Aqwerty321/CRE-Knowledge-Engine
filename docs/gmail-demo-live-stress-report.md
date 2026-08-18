# Gmail CRE demo — live CRUD stress report

Date: 2026-08-17

## Scope

The controlled live path used:

- sender: `aadityasoni2020@gmail.com`
- monitored/replying inbox: `aaditya@toolhouse.ai`
- Toolhouse Worker with Gmail, Google Sheets, and the custom Gmail CRE Demo MCP
- Google Sheets as the current property database
- one fresh, exact-subject Toolhouse run per test message

No Slack or Zapier path was used.

## Outcome

| Category | Live emails | Result |
|---|---:|---|
| CREATE | 5 | Rich listing, sparse listing, duplicate rejection, two-suite extraction, and footer-leakage cases exercised. |
| UPDATE | 5 | Partial merge, leased-status preservation, missing-target rejection, HVAC correction, and timing/provenance refresh exercised. |
| READ/QUERY | 5 | Exact row, repaired exact row, two-suite comparison, zero-hit behavior, and strict zero-hit backend composition exercised. |
| DELETE | 1 | Safely refused because the connected Google Sheets toolkit exposes no exact-row delete tool. No row was cleared or removed. |
| Replay | 1 | One checkpoint row remained; final Gmail reply-count check was rate-limited by the Gmail connector. |

The Sheet began with 30 seeded rows and ended with 35 rows. The delta is expected: Cypress (+1), Juniper (+1), Redwood Suites A/B (+2), and Limestone (+1). The attempted duplicate, missing-target update, and failed delete made no property-row changes.

## Repairs made during the run

1. The trigger now sends an exact-subject execution message to each fresh published-agent run instead of relying on the Agent Studio startup message.
2. Toolhouse status polling was slowed from three seconds to twelve seconds and now tolerates bounded transient failures.
3. Final Toolhouse result reads retry transient read timeouts.
4. A completed response containing only `Started` or missing-tool language is now treated as failure, not success.
5. Exact property questions now collapse BM25 neighbors to the named property/suite.
6. Property replies now render divisible range, office, clear height, voltage, docks, parking, and availability timing when supported.
7. Strict zero-hit questions can pass `exact_property_name` and `exact_suite`; the backend then returns no loose BM25 neighbors.
8. Natural phrases such as `full HVAC`, `100% HVAC`, and `existing clean room` normalize to confirmed feature states.
9. Successful listing projections always stamp the current Gmail source message, subject, and received time.

## Confirmed behavior

- Rich CREATE produced a stable `EMAIL-...` property ID and preserved stated CRE fields.
- Sparse CREATE left OPEX, power, HVAC, and parking unknown instead of inventing values.
- Duplicate CREATE returned `property_already_exists` and left the row count unchanged.
- One multi-suite email created exactly two rows and preserved suite-specific office, power, clean-room, and dock facts.
- The footer regression created no property for the legal-footer address or its bogus 99,999 SF/2,500A values.
- Partial UPDATE preserved the stable property ID and unspecified facts.
- `leased` updated status but did not delete the row.
- Missing-target UPDATE returned `property_not_found` and created nothing.
- Exact QUERY produced one grounded property instead of ten loose BM25 candidates after repair.
- A two-suite comparison returned exactly the two requested suites.
- Strict zero-hit QUERY sent the backend-composed no-result body with no suggestions.

## Remaining connector gaps

1. Physical DELETE is blocked until the Toolhouse Google Sheets connection exposes a tool that deletes exactly one row by stable key. The Worker correctly refuses to emulate deletion by clearing cells.
2. Toolhouse/Gmail intermittently returned TLS timeouts, OAuth `TOOL_AUTH_REQUIRED`, and HTTP 429. Fresh exact-subject runs recovered most transient cases, but connector latency ranged from about one minute to more than fifteen minutes.
3. The replay test retained one Sheet checkpoint, but the final Gmail reply-count inspection was blocked by a connector 429. Repeat that read-only check after the Gmail limit resets.
4. Republish the latest prompt in `docs/toolhouse-gmail-demo-agent-prompt.md` so exact identity fields and verbatim backend body sending are permanent Agent instructions rather than only run-time instructions.

## Next safe live action

After Gmail rate limits reset, perform a read-only count of outbound replies in the `QUERY 305` thread. Then connect an exact-row Google Sheets delete tool and retry the existing `DELETE 401` email; do not send a duplicate delete email.
