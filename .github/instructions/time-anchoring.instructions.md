---
name: Time Anchoring
description: Use the time MCP when exact time context matters.
applyTo: "**"
---
# Time anchoring guidance

- Use `timeLocal_get_current_time`, `timeLocal_get_current_date`, or `timeLocal_get_datetime_info` to anchor “now”, “today”, maintenance windows, release timing, deadlines, or schedule-sensitive planning.
- Use `timeLocal_format_timestamp` for logs, incidents, cron outputs, and timezone conversions.
- Prefer `timeLocal` over inference when time context affects the correctness or usefulness of the answer.
- Use time context productively for planning, incident reconstruction, status reporting, and date-sensitive creative work when the current date or time meaningfully shapes the output.
