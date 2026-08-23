# Release and GitHub Actions Verification Report

**Completed:** 2026-08-24  
**Repository:** `egemeny13/euroleague-analytics`

## Result

The reviewed E2026 release-readiness work was published through a feature
branch and pull request, passed GitHub Actions, and was merged without a direct
push to `master`. A real `workflow_dispatch` run then completed the fetch,
load, and Decision 7 settlement stages against the configured live services.

## Reviewed release

- Review branch: `codex/release-readiness-20260823`
- Pull request: [#2 — Release E2026 live pipeline readiness](https://github.com/egemeny13/euroleague-analytics/pull/2)
- Reviewed head: `d7bf7e2a12c8be4520c8dab4762a50823fb44f0e`
- Merge commit: `133389a49fa2df4ce4627fbda082d5ca39c46cf8`
- Reviewed range: 45 commits, 92 paths, 13,614 additions, 317 deletions
- Baseline: `907f228f432b525baecde0b65060bf1e57ffd1c9`

The range was zero commits behind and 45 commits ahead of the baseline. All
commits had the expected author. The largest blob was 85,251 bytes and no blob
exceeded 1 MiB. The sensitive-path audit found only the tracked
`.env.example`. A history scan found only deliberately fake credential-shaped
fixtures in security tests; it found no real token, private key, JWT, or
password-bearing database URI.

The repository currently has no GitHub branch-protection rule or ruleset for
`master`. This is an external policy gap, not permission to bypass review: the
release still used a feature branch and merge commit, and no direct
protected-branch push occurred.

## CI evidence

- Pull-request CI: [run 32668212623](https://github.com/egemeny13/euroleague-analytics/actions/runs/32668212623), success on `d7bf7e2`
- Post-merge CI: [run 32668283623](https://github.com/egemeny13/euroleague-analytics/actions/runs/32668283623), success on `133389a`
- Pull-request gate: `All checks passed!`, `97 files already formatted`,
  `653 passed, 83 deselected in 8.22s`

The 83 deselected tests are the repository's separately gated warehouse and
full-season checks; the successful PR run is evidence for the offline CI gate,
not a claim that those external-data suites ran in GitHub Actions.

## Real E2026 workflow evidence

- Workflow: `E2026 live pipeline`
- Run: [32668299705](https://github.com/egemeny13/euroleague-analytics/actions/runs/32668299705)
- Trigger: `workflow_dispatch`
- Branch and commit: `master` at `133389a49fa2df4ce4627fbda082d5ca39c46cf8`
- Job: `daily-fetch` (`97265093633`), success in 16 seconds
- Window: 2026-08-23 21:41:46–21:42:02 UTC

All three application stages completed successfully:

1. Fetch and archive: 380 scheduled, 0 played, 0 game responses, 1 file and
   680,836 bytes fetched, 0 skipped, 0 permanently unavailable, 0 failed,
   1 HTTP request, 1.5 seconds.
2. Load and derive: 380 scheduled, 0 played, 0 already loaded, 0 newly loaded.
3. Decision 7 settlement: no game owed a re-check.

These values drive the three `GITHUB_STEP_SUMMARY` blocks produced by
`format_fetch_summary`, `format_live_pipeline_summary`, and
`format_settlement_summary`. The successful-path headings and content were
cross-checked against `src/euroleague/step_summary.py`, the scripts' unconditional
summary writes, and the live run logs. Failure-path tests separately prove that
the first line names the failed stage.

## Credential redaction

GitHub masked `DATABASE_URL`, `SUPABASE_URL`, and
`SUPABASE_SERVICE_ROLE_KEY` as `***`. A scan of the downloaded job log found:

- 0 GitHub-token patterns
- 0 private-key headers
- 0 AWS access-key patterns
- 0 password-bearing PostgreSQL URIs
- 0 JWT patterns
- 0 Supabase secret-key patterns
- 0 secret-assignment lines
- 21 GitHub mask markers

The summary formatters emit only counts, game identifiers, elapsed time, and
sanitised failure messages. Their credential-exclusion behavior is covered by
`tests/test_nightly_summary.py`.

## External visibility limit

The public GitHub run page exposed the successful run, commit, branch, duration,
and job graph but required sign-in for logs and did not expose the rendered
summary bodies. The authenticated REST check-run response also returned a null
`output.summary`; the REST response did not return `GITHUB_STEP_SUMMARY`
content for this run. Therefore the rendered markdown was
validated through the exact live outputs, producer code paths, tests, and
successful step completion rather than copied back from an authenticated web
session. This is a documented observation limit, not evidence of a workflow
failure.

## Remaining operator notes

- Add a `master` ruleset requiring pull requests and the CI check if repository
  policy should enforce the review path technically.
- The live run correctly had zero played games on 2026-08-23; opening-week
  ingestion and settlement proof remain date-gated work.
- Release branches were not deleted because branch deletion was not part of the
  approved release action.
