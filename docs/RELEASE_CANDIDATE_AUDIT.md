# Release-candidate audit

Read-only audit of `master` at commit `beb5b85`, carried out on 2026-08-26.

## What this audit is, and what it is not

Every finding below came from reading the code, the migrations, the workflow
files and the tests. **No file was edited. No connection was made to the
production warehouse, and no request was made to the EuroLeague API.**

Two things were run, both locally and both harmless:

- The default offline test suite, in the working tree: **792 tests, all green.**
- The same suite from a **fresh `git clone` with no `.env` file present**, to
  check that somebody cloning this repository for the first time can run it:
  **also all green.**

Where a finding depends on what is actually in the production database, the
report says so and says what the claim rests on instead. Nothing here is
inferred from a single game, and nothing here is asserted without pointing at
the line that establishes it.

**The 14 quarantined E2024 games and 17 quarantined E2025 games are not treated
as defects.** They are the approved possession quarantine and are out of scope
for this audit.

## Summary

| # | Severity | Finding | Where |
|---|---|---|---|
| P0-1 | Blocker | `el_get_player_on_off` mixes seasons and can report a team the player never played for | `src/euroleague/mcp/queries.py:831` |
| P1-1 | High | A malformed `DATABASE_URL` prints the password into the public workflow log and job summary | `src/euroleague/config.py:147` |
| P1-2 | High | `total_available` is a guess in two of the ten tools, and nothing says so | `src/euroleague/mcp/queries.py:693`, `:804` |
| P1-3 | High | `include_quarantined` treats any non-empty string as true in nine of ten tools | `src/euroleague/mcp/queries.py:434` and seven others |
| P2-1 | Medium | Two tools page with a non-unique sort key, so paging can duplicate and drop rows | `src/euroleague/mcp/queries.py:681`, `:784` |
| P2-2 | Medium | The name resolver's ambiguity error is uncapped while every success path is capped | `src/euroleague/mcp/resolve.py:125` |
| P2-3 | Medium | `settlement_recheck.py`'s docstring states the opposite of what the rebuild does | `scripts/settlement_recheck.py:30` |
| P2-4 | Medium | `.env.example` names the live Supabase project | `.env.example:13`, `:33` |

Recommended order before tagging a release: **P0-1**, then **P1-1**. P1-2 and
P1-3 are both small edits that remove silently wrong numbers from a surface a
language model reads without scepticism.

---

## P0-1 — `el_get_player_on_off` mixes seasons, and can report a team the player never played for

**Location:** `src/euroleague/mcp/queries.py:831-835`

```sql
with player_lineups as (
    select lineup_id, team_code from v_lineup_player where player_id = %s
),
his_teams as (
    select distinct team_code from player_lineups{team_filter}
),
```

### In plain language

The on/off tool works in two steps. First it asks: *which five-man units has
this player ever been part of?* Then it uses the teams attached to those units
to decide **which teams to measure**.

The problem is in the first step. A "five-man unit" in this warehouse is
deliberately not tied to a season. `migrations/0003_derived_layer.up.sql:17-19`
says so in as many words:

> A checksum of the team code plus the five player ids in sorted order.
> Deterministic, so the same five always collapse to one identity in any game
> and **any season**.

The view the tool reads from, `v_lineup_player`
(`migrations/0004_query_views.up.sql:235-243`), carries no season column either.
So when the tool asks "which units has this player been in", the answer comes
back from **every season loaded in the warehouse**, not from the one that was
asked about. The list of teams built from that answer is therefore also
cross-season.

The possessions themselves *are* filtered to the requested season further down
the query. It is only the list of *which teams to look at* that leaks.

### Failure scenario

Both E2024 and E2025 are loaded in production (`README.md:18`).

TJ Shorts played for Paris (`PRS`) in E2024 and moved clubs for E2025. Ask the
tool about his E2024 on/off split **without** naming a team:

```json
{"season": "E2024", "player": "SHORTS, TJ"}
```

The tool builds its team list from both seasons, so it gets `{PRS, PAO}`. It
then measures **E2024 possessions for both clubs**. The result set comes back
with an extra row labelled `split: "off"`, `team_code: "PAO"` — which is simply
Panathinaikos's entire E2024 season, for a club Shorts was not on that year,
carrying an offensive rating, a defensive rating and a net rating like any other
row.

A model answering *"how did his team do without him?"* sees two teams, has no
signal that one of them is spurious, and there is no caveat in the response that
would let it tell.

Passing the optional `team` argument hides the bug entirely, because
`queries.py:826` then adds a `where team_code = %s` filter. That is why it has
never been seen.

### The test that would catch it

A warehouse test that calls `get_player_on_off` **without** a `team` argument,
for a player known to have changed clubs between two loaded seasons, and asserts
that exactly one distinct `team_code` comes back — the club he played for in the
requested season:

```python
response = get_player_on_off(cursor, {"season": "E2024", "player": "SHORTS, TJ"})
assert {row["team_code"] for row in response["rows"]} == {"PRS"}
```

### Why the existing tests cannot catch it

- `tests/test_phase_7_gate.py:258-262` is the only test that calls this tool
  without a team. It asserts `splits == {"on", "off"}`. That is a **set**, so
  two extra rows for a second club are invisible to it, and its other assertion
  (`possessions > 0`) is also satisfied by the spurious rows.
- Both evaluation tests that exercise this tool
  (`tests/test_phase_8_evaluations.py:248` and `:482`) pass `team=` explicitly,
  which activates the filter that hides the bug.
- The recorded ground-truth SQL in `evaluation.xml:157` hard-codes
  `l.team_code = 'PRS'`. **The published ground truth encodes the correct
  single-team semantics that the tool itself does not enforce.**

### Shape of the fix

`player_lineups` needs a season restriction, and the `lineup` table cannot
supply one on its own. The unit has to be reached through something that does
carry a season — `possession` or `lineup_stint` for the requested season — so
that only units the player actually appeared in *that year* contribute to the
team list.

---

## P1-1 — A malformed `DATABASE_URL` prints the password into the public workflow log and job summary

**Location:** `src/euroleague/config.py:147`

```python
raise ValueError(f"No host in the connection string {url!r}.")
```

### In plain language

The settings object that holds the database password is carefully built so that
printing it shows `password=<hidden>` instead of the real thing. The module's
own docstring at `config.py:98-99` explains why:

> The password is held in a field that `repr` does not print. Settings objects
> end up in tracebacks and CI logs, and this repository is public.

That guard works. But there is one error branch — the one that fires when the
connection string has no hostname — which puts **the whole raw connection
string, password included**, into the error message. The message then travels
past the guard, because it is a string, not a settings object.

### Where it comes out

All three steps of the nightly public workflow `.github/workflows/e2026-live.yml`
catch exceptions and print the message:

| Script | Lines | What it does with the message |
|---|---|---|
| `scripts/fetch_archive.py` | `139-140` | writes it to the job summary, then to stderr |
| `scripts/live_pipeline.py` | `116-117` | writes it to the job summary, then to stderr |
| `scripts/settlement_recheck.py` | `219-220` | writes it to the job summary, then to stderr |

Each of those sits directly under a comment promising the opposite. For example
`live_pipeline.py:114-115`:

> The message, never the settings object: a traceback carrying a connection
> string would land in a public log.

In this one case the message **is** the settings.

### Reproduced

Running the production code path with a hostless connection string:

```
STDERR LINE -> Live pipeline failed: ValueError: No host in the connection string
'postgresql://postgres.abcdefghijklmnop:S3cr3t-P4ssw0rd!@:5432/postgres'.
```

The same text is what gets written into the GitHub Actions job summary.

### Failure scenario

The `DATABASE_URL` repository secret is re-pasted and loses its host — a
truncated copy, an editor eating a line, a rotated password pasted wrong. The
scheduled 03:43 run fails, and the full connection string with the live password
lands in the job summary and stderr of a **public** repository's Actions log.

GitHub masks registered secret values in the log *stream*, which softens the
stderr path. Job summaries are rendered through a different path and that
masking should not be relied on there. Locally, running the same script with a
broken `.env` prints the password to the terminal with no masking at all.

### The test that would catch it

A test for exactly this already exists and is even named for it —
`tests/test_nightly_summary.py:84-100`, `test_summaries_never_carry_credentials`.
It calls the three summary formatters only on their **success** paths, so it has
never exercised the branch that can carry a secret.

Extend it to the failure branch:

```python
failure = None
try:
    DatabaseSettings.from_url("postgresql://u:S3cr3t-P4ssw0rd@:5432/db")
except ValueError as error:
    failure = error

for block in (
    format_fetch_summary("E2026", [], failure=failure),
    format_live_pipeline_summary("E2026", None, failure=failure),
    format_settlement_summary("E2026", None, failure=failure),
):
    assert "S3cr3t-P4ssw0rd" not in block
```

That test fails today. A second test should assert that `from_url` never
interpolates the raw `url` into any message it raises.

---

## P1-2 — `total_available` is a guess in two of the ten tools, and nothing says so

**Location:** `src/euroleague/mcp/queries.py:693` (`get_player_stats`) and
`src/euroleague/mcp/queries.py:804` (`get_lineup_stats`)

```python
total_available=offset + len(rows) + (1 if len(rows) == limit else 0),
```

### In plain language

Every response carries a field called `total_available`, meaning *how many rows
match your filter in total, before paging*. Four of the paginated tools compute
it honestly: they run a separate counting query first
(`queries.py:376`, `:466`, `:946`, `:1008`).

These two do not. They compute it as *"the number of rows I just handed you,
plus one if there might be more"*. On any page except the last, that number is
wrong, and it is wrong by however much data was not returned.

The field is named identically to the honest one, and nothing in the tool
descriptions, the response caveats, or the documentation marks it as an
estimate.

### Failure scenario

Suppose 380 players in E2024 clear a `min_seconds` filter. A model calls
`el_get_player_stats` with the default page size of 50 and reads:

```json
"total_available": 51
```

It answers *"51 players qualified."* The real answer is 380. The number is off
by an order of magnitude, is presented in the same field that is exact
elsewhere, and carries no warning.

This is made worse by `docs/SHOT_DATA_TOOL_REPORT.md:120`, which explicitly
tells a model to use this field rather than counting the current page. That is
good advice for `el_get_shot_data`, where the number is exact, and actively
harmful for these two.

Paging itself still works correctly — `truncated` and `next_offset` are derived
consistently at `envelope.py:171-173`. It is only the total that is fictional.

### The test that would catch it

An invariant test across every paginated tool: call each one twice with the same
filter, once with a small page size and once with the maximum, and assert
`total_available` is identical.

```python
small = tool(cursor, {**arguments, "limit": 5})
large = tool(cursor, {**arguments, "limit": 200})
assert small["total_available"] == large["total_available"]
```

That holds today for the four exact tools and fails for these two.

`tests/test_phase_7_gate.py:242` already compares `total_available` between two
calls, but with identical arguments — so it proves the number is *stable*, not
that it is *right*.

---

## P1-3 — `include_quarantined` treats any non-empty string as true in nine of ten tools

**Locations:** `src/euroleague/mcp/queries.py:434, 491, 558, 634, 762, 818, 900, 986`

```python
include_quarantined = bool(arguments.get("include_quarantined", False))
```

Also `per_game` at `:647` and `aggregate` at `:930`.

### In plain language

In Python, converting the text `"false"` to a yes/no value gives **yes**,
because the rule is "any non-empty piece of text counts as true". So a caller
who sends the word `"false"` instead of the value `false` gets the opposite of
what they asked for.

This exact hazard was already identified and fixed — but in only one tool.
`get_shot_data` at `:336` uses a strict reader, `_shot_boolean` (`:290-296`),
whose docstring says precisely this:

> Read an optional JSON Boolean without treating non-empty strings as true.

The other nine tools use the loose conversion.

### Failure scenario

A model emits a routine JSON typing slip:

```json
{"season": "E2024", "include_quarantined": "false"}
```

The tool reads that as *true*. All 14 quarantined E2024 games are silently
included in an answer the caller believed it had asked to be clean — inverting
`CLAUDE.md`'s rule that quarantined games are excluded from every default
answer.

The response envelope does state that quarantined games were included, so it is
not wholly silent. But the note reads *"at your request"*, which is untrue, and
`game_coverage` (`:113-146`, used by `el_get_game` and `el_get_play_by_play`)
does not even carry the `include_quarantined` field for a model to cross-check
against what it sent.

The same slip on `per_game`:

```json
{"season": "E2024", "per_game": "false"}
```

silently converts season totals into per-game averages — a factor-of-thirty
error in every counting statistic returned.

### The test that would catch it

A test that walks the whole registered tool list and asserts each one rejects a
string where a Boolean belongs, naming the argument:

```python
for name, tool in registry.items():
    with pytest.raises(ValueError, match="include_quarantined"):
        tool.handler({"season": "E2024", "include_quarantined": "false"})
```

`el_get_shot_data` already behaves this way and `tests/test_shot_tool.py`
already covers it for that one tool. The gap is that the assertion was never
extended to the registry.

---

## P2-1 — Two tools page with a non-unique sort key, so paging can duplicate and drop rows

**Locations:**
`src/euroleague/mcp/queries.py:681` — `order by points desc nulls last limit %s offset %s`
`src/euroleague/mcp/queries.py:784` — `order by net_rating desc nulls last limit %s offset %s`

### In plain language

When you ask a database for "the first 50 rows sorted by points", and several
rows have the *same* number of points, the database is free to put those tied
rows in whatever order is convenient at that moment. Ask again for "rows 51 to
100" and it may order the tied group differently. The result is that a tied row
can appear on both pages, and another tied row can appear on neither.

Fixing this needs a tiebreaker — a second sort column that is unique. The four
tools that page correctly all have one: `utc_date, gamecode` (`:474`),
`gamecode, ingest_index` (`:383`), `gamecode, possession_index` (`:953`), and
`ingest_index` (`:1016`). These two have none.

### Failure scenario

A model pages through E2024 lineups with `min_possessions=10`. Net rating is
rounded to two decimal places, so ties are common across thousands of units.

Page 1 (`offset=0`) and page 2 (`offset=50`) can both contain the same tied
lineup, while a different tied lineup appears on neither. The model assembles a
leaderboard that double-counts one unit and silently omits another. Nothing
errors, and the result looks entirely plausible.

### The test that would catch it

Fetch the whole result in one call, then page the same filter in small pages,
and assert the two identifier sequences match:

```python
whole = get_lineup_stats(cursor, {**arguments, "limit": 200})
paged = []
for offset in range(0, 200, 10):
    page = get_lineup_stats(cursor, {**arguments, "limit": 10, "offset": offset})
    paged.extend(row["lineup_id"] for row in page["rows"])
assert paged == [row["lineup_id"] for row in whole["rows"]]
```

### Shape of the fix

Append `, lineup_id` and `, player_id` to the two `order by` clauses.

---

## P2-2 — The name resolver's ambiguity error is uncapped while every success path is capped

**Locations:** `src/euroleague/mcp/resolve.py:125-130` (players) and `:85-90` (teams)

```python
listed = ", ".join(f"{player_id} ({name})" for player_id, name in rows)
raise AmbiguousNameError(
    f"{candidate!r} matches {len(rows)} players in {season_code}: {listed}. "
    f"Pass one of these player ids."
)
```

### In plain language

The project caps every successful answer at 200 rows, and says why —
`clamp_limit` at `queries.py:37-43` exists to *"keep a result set inside the
model's context window"*.

That cap governs rows a tool **returns**. It does not govern rows an **error
message lists**. When a name is ambiguous, the resolver names every single match
in one block of text, with no upper bound.

A secondary detail: the name search builds its pattern as
`"%" + what_you_typed + "%"`, at `:120` and `:80`. In database search syntax,
`%` and `_` are wildcards, so those characters typed by a caller are treated as
"match anything" rather than as literal characters. This is *not* a security
hole — the value is still passed safely as a parameter — but it means a single
character is enough to match every name in the season.

### Failure scenario

A model calls:

```json
{"season": "E2024", "player": "a"}
```

or, having read that names are stored `SURNAME, FORENAME`, tries `"_"`. Every
player in the season matches. The tool error returned through
`protocol.py:148-151` is one text block naming several hundred players with
their identifiers. It consumes a large slice of the model's context window to
convey nothing, and the text is not truncated anywhere on the way out.

### The test that would catch it

An offline test with a stubbed cursor returning 400 ambiguous rows, asserting
the raised message stays under a fixed byte budget and ends with an instruction
naming how many further matches were suppressed:

```python
with pytest.raises(AmbiguousNameError) as failure:
    resolve_player(cursor_with_400_matches, "E2024", "a")
assert len(str(failure.value)) < 1000
assert "and 390 more" in str(failure.value)
```

`tests/test_mcp_resolve.py:152` and `:179` assert the ambiguity error is
*raised* but say nothing about its size.

---

## P2-3 — `settlement_recheck.py`'s docstring states the opposite of what the rebuild does

**Location:** `scripts/settlement_recheck.py:30-34`

> WHY ONLY THE LIVE SEASON IS EVER REBUILT. The rebuild deliberately leaves
> `raw_shot` alone, because the live pipeline that loads E2026 never writes it.

The rebuild it calls does the opposite. `src/euroleague/live.py:203-205`:

> POINTS MOVES WITH THE GAME. The live writer now loads `raw_shot`, so a revised
> Points body is staged and replaced inside the same transaction as the other
> raw and derived rows.

And the code follows that second comment: `live.py:262` stages `raw_shot` rows
and `live.py:274` deletes them, both inside the same transaction.

### Why this matters even though the code is correct

This is not a runtime defect. The rebuild itself is sound — the transaction at
`live.py:259-284` stages everything before deleting anything, and the delete
ordering documented at `derived_load.py:587-600` correctly avoids the
`on delete set null` trap on the composite foreign keys.

The risk is operational, and it has two edges:

1. **Diagnosis.** When the first real E2026 source revision arrives — Order 8,
   which cannot run before the first game is played — whoever is investigating
   reads the entry-point docstring, concludes `raw_shot` was untouched, and
   looks for a coordinate discrepancy somewhere it is not.
2. **Argument.** The same paragraph is given as the *reason* the E2026-only
   season restriction exists (`settlement_recheck.py:111-118`). Any future
   decision to widen that restriction would be argued from a premise that is no
   longer true.

### The test that would catch it

Nothing mechanical catches a stale comment. The nearest useful thing is to pin
the behaviour so the contradiction becomes visible from test names:
`tests/test_rebuild_revised_game.py` should assert `raw_shot` appears in the
returned `RebuildSummary.counts`.

The docstring itself needs a hand edit.

---

## P2-4 — `.env.example` names the live Supabase project

**Locations:** `.env.example:13` and `.env.example:33`

The example file carries the real project reference `pctiewdpstnwcutrvegu` three
times — as a hostname (`db.pctiewdpstnwcutrvegu.supabase.co`), as a database
user (`postgres.pctiewdpstnwcutrvegu`), and as
`SUPABASE_URL=https://pctiewdpstnwcutrvegu.supabase.co`.

### Failure scenario

The project reference is not itself a secret; it appears in any client URL. But
this repository is public, and the file hands a reader the exact host, the exact
database role name, and confirmation that the session pooler is reachable on
port 5432. That reduces an attack on the warehouse to guessing one password
against a named, confirmed endpoint.

The rest of the same file is careful about precisely this. `.env.example:2`:

> Copy this file to .env and fill in the real value. .env is gitignored and must
> never be committed - this repository is public.

Which is what makes the concrete identifier stand out.

### The test that would catch it

A repository-hygiene assertion that `.env.example` contains no string matching
Supabase's project-reference shape (twenty lowercase letters).
`tests/test_ci_configuration.py` is the natural home:

```python
text = Path(".env.example").read_text(encoding="utf-8")
assert re.search(r"\b[a-z]{20}\b", text) is None
```

### Shape of the fix

Replace the reference with `<your-project-ref>` in both places.

---

## What was checked and found clean

These are the areas the audit was asked to prioritise. Each was examined and no
defect was found. Listing them matters as much as listing the findings: a check
that is not recorded is a check nobody can tell was done.

### Write paths through the read-only MCP server

Every statement in `queries.py` is a `select`. The session is proved read-only
at connect time rather than assumed — `db.py:86-96` issues the read-only setting
and then asks the database to confirm it took effect, refusing to serve queries
if it did not. The reasoning for using a post-connect setting rather than a
startup parameter (`db.py:7-14`) is correct for Supabase's shared pooler, which
rejects startup parameters it does not recognise.

`migrations/0011_public_view_security.up.sql` closes all seven warehouse views
to the `anon` and `authenticated` roles and makes them obey the caller's
permissions rather than the owner's. Every base table has row-level security
enabled with no policies, which denies all access to those roles.

One residual note, not a defect: the server connects as the project's `postgres`
role, so the read-only guarantee rests entirely on that one setting. A dedicated
read-only database role would make it structural rather than procedural. **No
reachable path that writes was found.**

### SQL injection

Every caller-supplied value is passed as a bound parameter, never pasted into
the SQL text. The pieces of SQL that *are* assembled as text are fixed clauses
chosen by the module itself:

- `" and ".join(conditions)` where every condition is a literal string
- `_quarantine_clause` (`queries.py:51-53`), which returns one of two fixed
  strings
- the minutes-column and divisor lookups at `queries.py:653-661` and `:664`,
  both from closed sets
- the table name in `derived_load.py:608`, from a fixed tuple

Parameter order matches textual order in every composed statement, including the
four-part on/off query, which was checked clause by clause.

### Play-by-play event reordering

`events.py:8-14` lists the five period arrays in the correct order, including
the API's `ForthQuarter` misspelling, and `events.py:109` assigns `ingest_index`
by walking them in array order. **Nothing sorts the event stream.**

The three `sorted()` calls in the derived layer (`derived.py:726`,
`lineups.py:130`) operate on already-derived index pairs, not on events.
`v_play_by_play` and `get_play_by_play` both order by `ingest_index` alone, and
the tool's response carries a caveat telling the model not to re-sort.

### Unbounded MCP output

Every row-returning path is capped at 200 rows by `clamp_limit`. The three tools
without an explicit limit are bounded by the data itself: `el_get_team_stats`
and the aggregate mode of `el_get_possessions` return one row per team,
`el_get_player_on_off` returns at most two rows per team, and
`el_describe_warehouse` returns one row per season plus one per team-season. The
only uncapped text path found is the resolver error in **P2-2**.

### Connection reuse, reconnect, concurrency and pooler behaviour

The connection manager (`db.py:51-74`) opens one connection lazily, reuses it
across calls, opens a fresh cursor for each one, and retries exactly once on a
dropped connection — going back through the verifying connect function, so a
replacement connection is proved read-only too. There is no path that returns
without a result.

The server reads requests one line at a time from a single thread
(`protocol.py:170`), so there is no concurrent use of the shared connection.

`config.py` refuses both of the two wrong Supabase connection strings with an
explanation: the direct host, which is IPv6-only on the free plan and so works
locally and fails in CI, and the transaction pooler, which does not support
prepared statements and so fails partway through a bulk load.

### Atomic one-game rebuild

`live.py:207-284` was traced end to end and is sound:

- Everything that can refuse does so **before** the transaction opens, so a
  refusal leaves the warehouse untouched.
- Rows are staged before anything is deleted, so a body that no longer parses
  fails before any stored row is removed.
- `game_event` is deleted before the rows it references, which avoids a real
  trap documented at `derived_load.py:589-598`: two foreign keys are declared
  `on delete set null`, and letting them fire would try to null a column that
  cannot be null.
- Dimension writes are narrowed to the one game's own players and teams.
- The applied-checksum marker advances inside the same transaction, so a failed
  rebuild stays pending and is retried rather than forgotten.
- Every staging table is created `on commit drop`, so a repair loop over several
  revised games cannot collide with itself.

### Clean-clone onboarding

A fresh `git clone` with no `.env` file runs the full default test suite green.
The committed fixtures are present and sufficient; nothing in the default path
needs the response cache, the network, or the warehouse.

---

## Method note

This audit reasoned from source. It did not query the production warehouse, so
the P0-1 failure scenario is established from the schema comment that makes
`lineup` season-less, the view definition that carries no season column, and the
query text that joins them — not from a returned row. The season-mixing is a
property of the query as written; whether any *particular* player produces the
spurious row depends on which seasons are loaded and who transferred.
