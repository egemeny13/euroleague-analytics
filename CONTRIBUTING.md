# Contributing and Reporting Issues

Thank you for testing and using the EuroLeague Analytics warehouse.

## How to Report Observations and Issues

If you notice a discrepancy, unexpected result, or missing data while using
the MCP server or warehouse:

1. **Check `el_describe_warehouse` first**: Call `el_describe_warehouse` to see
   which seasons are loaded and which games are quarantined. A game missing from
   default query results is often one that was quarantined due to un-reconcilable
   official source events rather than a bug.
2. **File a GitHub Issue**: Open an issue on this repository using the issue
   template.

## What a Good Report Contains

To make your report actionable and reproducible, please include:

- **Season**: The season code queried (e.g. `E2024`, `E2025`, `E2026`).
- **Tool called & arguments**: The exact MCP tool name (e.g. `el_get_lineup_stats`)
  and the arguments provided.
- **Answer received**: The exact response returned by the tool.
- **Answer expected**: What you expected to see and why.
- **Minutes basis**: Whether the tool response declared minutes as `raw` or
  `corrected` (every minutes-bearing response states its basis).

## How Reports Are Processed

Reports filed as GitHub issues are triaged by the maintainers into repository
inbox items (`docs/goals/inbox.md`). Each verified issue is then formalized into a
goal contract with automated validation tests via `/define-goal` and implemented
through the project's development pipeline.
