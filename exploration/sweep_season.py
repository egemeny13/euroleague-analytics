"""Replay the lineup reconstruction over every cached game of a season.

Reads only from the on-disk cache written by fetch_season.py. Never touches the
network. Fixes nothing: this script finds and describes problems, it does not
repair them.

The reconstruction is deliberately the same naive one that was tested on a
single game in FINDINGS.md:

  1. Seed each team's on-court five from the box score IsStarter flag.
  2. Walk the events in the order the arrays give them. Never sort.
  3. Apply every IN and every OUT.

Everything else in this file is measurement of what that reconstruction does.
"""

import collections
import glob
import json
import os
import re

SEASON = "E2024"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_ROOT = os.path.join(HERE, "cache", SEASON)
RESULTS_PATH = os.path.join(HERE, "sweep_results.json")

# The play-by-play is five separate lists. Their order is chronological order.
# 'ForthQuarter' is misspelled in the API; that is not a typo here.
PERIOD_LISTS = ("FirstQuarter", "SecondQuarter", "ThirdQuarter",
                "ForthQuarter", "ExtraTime")

QUARTER_SECONDS = 600
OVERTIME_SECONDS = 300

# Play types that carry a player and represent something that happened on the
# floor. Used for the "was this player actually on court?" check.
SUBSTITUTION_TYPES = {"IN", "OUT"}

# The play-by-play credits bench technical fouls to a pseudo-player: CO_A and
# CO_B are the two head coaches, AC_A and AC_B the two assistant coaches
# (A = home team, B = away team). These are not players, they are never on
# court, and the id is positional rather than a stable person key: CO_A means
# a different human in every game. They must be excluded from on-court checks.
COACH_ID_PREFIXES = ("CO_", "AC_")


def clean(value):
    """Trim a field. Every ID and team code in this API is space padded."""
    if value is None:
        return ""
    return str(value).strip()


def playtype(event):
    return clean(event.get("PLAYTYPE"))


def parse_clock(text):
    """Turn a 'MM:SS' countdown string into seconds remaining in the period."""
    text = clean(text)
    if not text or ":" not in text:
        return None
    minutes, _, seconds = text.partition(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def parse_minutes(text):
    """Turn a box score 'MM:SS' played string into seconds.

    Returns None for a player who did not play. The API writes 'DNP' for
    those, and null for the team-rebound pseudo-row.
    """
    text = clean(text)
    if not text or text.upper() == "DNP":
        return None
    return parse_clock(text)


def period_start_seconds(period):
    """Seconds from tip-off to the start of a period. Periods 5+ are overtime."""
    if period <= 4:
        return (period - 1) * QUARTER_SECONDS
    return 4 * QUARTER_SECONDS + (period - 5) * OVERTIME_SECONDS


def period_length_seconds(period):
    return QUARTER_SECONDS if period <= 4 else OVERTIME_SECONDS


def flatten_events(pbp):
    """Concatenate the five lists into one stream, tagging each event's period.

    Order is preserved exactly as the API gave it. For the first four lists the
    period is simply which list the event came from. 'ExtraTime' is a single
    list that may hold more than one overtime period, so overtime periods are
    counted off by their 'BP' (begin period) markers.
    """
    stream = []
    for index, key in enumerate(PERIOD_LISTS):
        raw = pbp.get(key) or []
        if key != "ExtraTime":
            for event in raw:
                stream.append((index + 1, event))
        else:
            # 'ExtraTime' is one list that can hold several overtime periods.
            # The obvious split point is the 'BP' (begin period) marker, but
            # that is wrong: the substitutions that open an overtime are
            # written *before* its BP marker. Splitting on BP would credit
            # them to the previous period and misplace them by five minutes.
            #
            # So a new overtime starts immediately after the previous 'EP'
            # (end period) marker instead. The closing 'EG' (end game) marker
            # trails the final EP and stays with the period it ends.
            overtime_number = 1
            start_new_period = False
            for event in raw:
                kind = playtype(event)
                if start_new_period and kind != "EG":
                    overtime_number += 1
                    start_new_period = False
                stream.append((4 + overtime_number, event))
                if kind == "EP":
                    start_new_period = True
    return stream


def event_elapsed_seconds(period, event, previous):
    """Seconds from tip-off for one event.

    Most events carry MARKERTIME, a countdown within the period. The handful
    that do not are the structural markers, and those sit exactly on a period
    boundary. Anything else without a clock inherits the previous event's time.
    """
    start = period_start_seconds(period)
    length = period_length_seconds(period)
    remaining = parse_clock(event.get("MARKERTIME"))
    if remaining is not None:
        return start + (length - remaining)
    kind = playtype(event)
    if kind == "BP":
        return start
    if kind in ("EP", "EG"):
        return start + length
    return previous


def load_boxscore_players(boxscore):
    """Pull the per-player box score rows out, keyed by team code then player.

    Returns (players, problems). players maps team code -> player id -> row.
    The team-rebound pseudo-row has a blank player id and is skipped.
    """
    players = collections.OrderedDict()
    problems = []
    for team_block in boxscore.get("Stats") or []:
        for row in team_block.get("PlayersStats") or []:
            team = clean(row.get("Team"))
            player_id = clean(row.get("Player_ID"))
            if not team or not player_id:
                continue
            if team not in players:
                players[team] = collections.OrderedDict()
            if player_id in players[team]:
                problems.append(f"duplicate box score row for {player_id} ({team})")
            players[team][player_id] = row
    return players, problems


def clock_groups(stream):
    """Split the stream into runs of consecutive events sharing one clock reading.

    A stoppage produces a batch of IN and OUT rows all stamped at the same
    second, in arbitrary order, and the API sometimes drops an unrelated row
    (a free throw, an assist) into the middle of that batch. Inside such a
    batch the on-court count is briefly wrong by construction, which says
    nothing about the reconstruction. Grouping lets each batch be treated as
    one atomic swap, the way FINDINGS.md recommended.

    Yields (start_index, end_index_exclusive) pairs.
    """
    if not stream:
        return
    start = 0
    for index in range(1, len(stream) + 1):
        if index == len(stream):
            yield start, index
            break
        previous_period, previous_event = stream[index - 1]
        period, event = stream[index]
        same = (period == previous_period
                and clean(event.get("MARKERTIME"))
                == clean(previous_event.get("MARKERTIME")))
        if not same:
            yield start, index
            start = index


def minutes_with_monotonic_clock(box_players, stream, last_period):
    """Re-run the minutes reconstruction, but forbid the clock going backwards.

    This exists purely as a control experiment. The event stream occasionally
    stamps an event earlier than the one before it. The tempting "safe" fix is
    to clamp the clock so it never moves backwards. This function applies that
    clamp so the sweep can measure what the clamp costs, by comparing the
    resulting minutes against the official box score.
    """
    on_court = {team: set() for team in box_players}
    came_on = {team: {} for team in box_players}
    seconds = collections.Counter()
    for team in box_players:
        for player, row in box_players[team].items():
            if row.get("IsStarter") in (1, "1", True):
                on_court[team].add(player)
                came_on[team][player] = 0

    previous = 0
    for period, event in stream:
        elapsed = max(event_elapsed_seconds(period, event, previous), previous)
        kind = playtype(event)
        team = clean(event.get("CODETEAM"))
        player = clean(event.get("PLAYER_ID"))
        if kind == "IN" and team in on_court and player:
            if player not in on_court[team]:
                on_court[team].add(player)
                came_on[team][player] = elapsed
        elif kind == "OUT" and team in on_court and player:
            if player in on_court[team]:
                seconds[(team, player)] += elapsed - came_on[team].pop(player, elapsed)
                on_court[team].discard(player)
        previous = elapsed

    end = period_start_seconds(last_period) + period_length_seconds(last_period)
    for team in on_court:
        for player in list(on_court[team]):
            seconds[(team, player)] += end - came_on[team].pop(player, end)

    mismatches = []
    for team in box_players:
        for player, row in box_players[team].items():
            official = parse_minutes(row.get("Minutes"))
            if official is None:
                continue
            delta = seconds.get((team, player), 0) - official
            if delta:
                mismatches.append(delta)
    return mismatches


def reconstruct_game(gamecode, boxscore, pbp):
    """Run the reconstruction on one game and report everything it noticed."""
    report = {
        "gamecode": gamecode,
        "fatal": None,
        "teams": [],
        "overtime_periods": 0,
        "event_count": 0,
        "checks": {},
    }

    box_players, box_problems = load_boxscore_players(boxscore)
    report["boxscore_problems"] = box_problems

    teams = list(box_players.keys())
    report["teams"] = teams
    if len(teams) != 2:
        report["fatal"] = f"expected 2 teams in box score, found {len(teams)}"
        return report

    # --- 1. Seed the opening five from IsStarter -------------------------
    on_court = {team: set() for team in teams}
    starter_counts = {}
    for team in teams:
        starters = [pid for pid, row in box_players[team].items()
                    if row.get("IsStarter") in (1, "1", True)]
        starter_counts[team] = len(starters)
        on_court[team] = set(starters)
    report["starter_counts"] = starter_counts
    report["starters_ok"] = all(count == 5 for count in starter_counts.values())

    stream = flatten_events(pbp)
    report["event_count"] = len(stream)
    if not stream:
        report["fatal"] = "play-by-play contains no events"
        return report

    periods_seen = sorted({period for period, _ in stream})
    last_period = max(periods_seen)
    report["overtime_periods"] = max(0, last_period - 4)
    report["periods_seen"] = periods_seen

    # came_on[team][player] = elapsed seconds when the player last entered.
    came_on = {team: {} for team in teams}
    for team in teams:
        for player in on_court[team]:
            came_on[team][player] = 0
    seconds_played = collections.Counter()

    oncourt_violations = []
    double_in = []
    double_out = []
    phantom_events = []
    unknown_players = []
    clock_backwards = []
    in_counts = collections.Counter()
    out_counts = collections.Counter()
    phantom_by_playtype = collections.Counter()
    coach_events = collections.Counter()
    # Where a player was last substituted out, so a phantom event can be
    # described as "credited N rows after that player left, same clock reading".
    last_out = {}

    previous_elapsed = 0
    strict_oncourt_violations = 0
    group_bounds = {}
    for group_start, group_end in clock_groups(stream):
        for index in range(group_start, group_end):
            group_bounds[index] = (group_start, group_end)
    # On-court sets as they stood before the current batch of substitutions.
    before_group = {team: set(on_court[team]) for team in teams}
    pending_attributions = []

    for position, (period, event) in enumerate(stream):
        group_start, group_end = group_bounds[position]
        if position == group_start:
            before_group = {team: set(on_court[team]) for team in teams}
            during_group = {team: set(on_court[team]) for team in teams}
            pending_attributions = []
        elapsed = event_elapsed_seconds(period, event, previous_elapsed)
        kind = playtype(event)

        # Record, but do not correct, the clock going backwards. The list order
        # is the truth; the timestamp is what is slightly wrong.
        if elapsed < previous_elapsed:
            clock_backwards.append({
                "position": position,
                "period": period,
                "playtype": kind,
                "seconds_back": previous_elapsed - elapsed,
                "markertime": clean(event.get("MARKERTIME")),
                "is_substitution": kind in SUBSTITUTION_TYPES,
            })

        team = clean(event.get("CODETEAM"))
        player = clean(event.get("PLAYER_ID"))

        if kind == "IN" and team in on_court and player:
            in_counts[(team, player)] += 1
            if player in on_court[team]:
                double_in.append({"position": position, "period": period,
                                  "team": team, "player": player,
                                  "markertime": clean(event.get("MARKERTIME"))})
            else:
                on_court[team].add(player)
                came_on[team][player] = elapsed
        elif kind == "OUT" and team in on_court and player:
            out_counts[(team, player)] += 1
            if player not in on_court[team]:
                double_out.append({"position": position, "period": period,
                                   "team": team, "player": player,
                                   "markertime": clean(event.get("MARKERTIME"))})
            else:
                seconds_played[(team, player)] += elapsed - came_on[team].pop(player, elapsed)
                on_court[team].discard(player)
                last_out[(team, player)] = (position, clean(event.get("MARKERTIME")))
        else:
            # Strict reading: count the floor at this exact row. Inside a
            # substitution batch this is expected to wobble, so it is recorded
            # as a diagnostic rather than as a failure.
            for check_team in teams:
                if len(on_court[check_team]) != 5:
                    strict_oncourt_violations += 1
            if player.startswith(COACH_ID_PREFIXES):
                coach_events[kind] += 1
            elif player and team in on_court:
                if player not in box_players.get(team, {}):
                    unknown_players.append({"position": position, "team": team,
                                            "player": player, "playtype": kind})
                else:
                    # Judged at the end of the batch, against everyone who was
                    # on court either side of the swap.
                    pending_attributions.append((position, period, team, player,
                                                 kind,
                                                 clean(event.get("MARKERTIME"))))

        previous_elapsed = elapsed
        # Remember everyone who stood on the floor at any point inside this
        # batch. A player can enter and leave at the same clock reading, and
        # anything he did in between is legitimate.
        for check_team in teams:
            during_group[check_team] |= on_court[check_team]

        # End of this clock reading: the swap is complete, so the floor must
        # hold exactly five and every credited player must have been on it.
        if position == group_end - 1:
            for check_team in teams:
                if len(on_court[check_team]) != 5:
                    oncourt_violations.append({
                        "position": position, "period": period,
                        "team": check_team, "count": len(on_court[check_team]),
                        "playtype": kind,
                        "markertime": clean(event.get("MARKERTIME")),
                    })
            for (pos, per, tm, pid, knd, markertime) in pending_attributions:
                on_at_any_point = during_group.get(tm, set())
                if pid not in on_at_any_point:
                    phantom_by_playtype[knd] += 1
                    out_position, out_markertime = last_out.get((tm, pid),
                                                                (None, None))
                    phantom_events.append({
                        "position": pos, "period": per, "team": tm,
                        "player": pid, "playtype": knd,
                        "markertime": markertime,
                        "rows_since_out": (pos - out_position
                                           if out_position is not None else None),
                        "same_clock_as_out": (out_markertime == markertime
                                              if out_markertime else False),
                    })
            pending_attributions = []

    # --- 4. Close out anyone still on court at the final buzzer ----------
    game_end = period_start_seconds(last_period) + period_length_seconds(last_period)
    for team in teams:
        for player in list(on_court[team]):
            seconds_played[(team, player)] += game_end - came_on[team].pop(player, game_end)

    report["game_seconds"] = game_end

    # --- 5. Compare reconstructed minutes with the official box score ----
    minute_deltas = []
    for team in teams:
        for player, row in box_players[team].items():
            official = parse_minutes(row.get("Minutes"))
            reconstructed = seconds_played.get((team, player), 0)
            if official is None:
                # Box score says the player did not play.
                if reconstructed != 0:
                    minute_deltas.append({"team": team, "player": player,
                                          "name": clean(row.get("Player")),
                                          "official": None,
                                          "reconstructed": reconstructed,
                                          "delta": reconstructed})
                continue
            delta = reconstructed - official
            if delta != 0:
                minute_deltas.append({"team": team, "player": player,
                                      "name": clean(row.get("Player")),
                                      "official": official,
                                      "reconstructed": reconstructed,
                                      "delta": delta})

    report["minute_deltas"] = minute_deltas
    report["max_abs_minute_delta"] = max(
        (abs(entry["delta"]) for entry in minute_deltas), default=0)
    report["players_with_delta"] = len(minute_deltas)
    report["players_compared"] = sum(len(box_players[team]) for team in teams)

    # --- 6. Team minute totals: 200 minutes per regulation game, +25 per OT
    team_totals = {}
    for team in teams:
        total = sum(value for (t, _), value in seconds_played.items() if t == team)
        team_totals[team] = {
            "reconstructed_seconds": total,
            "expected_seconds": 5 * game_end,
            "delta_seconds": total - 5 * game_end,
        }
        official_total = sum(
            parse_minutes(row.get("Minutes")) or 0
            for row in box_players[team].values())
        team_totals[team]["official_seconds"] = official_total
        team_totals[team]["official_delta_seconds"] = official_total - 5 * game_end
    report["team_totals"] = team_totals

    # --- 7. Every IN must pair with an OUT -------------------------------
    # Over a whole game, for each player:
    #   (started?) + number of INs  ==  number of OUTs + (still on at the end?)
    pairing_errors = []
    for team in teams:
        for player in box_players[team]:
            started = 1 if box_players[team][player].get("IsStarter") in (1, "1", True) else 0
            ins = in_counts[(team, player)]
            outs = out_counts[(team, player)]
            ended_on = 1 if player in on_court[team] else 0
            if started + ins != outs + ended_on:
                pairing_errors.append({
                    "team": team, "player": player,
                    "started": started, "ins": ins, "outs": outs,
                    "ended_on_court": ended_on,
                })
    report["pairing_errors"] = pairing_errors

    report["strict_oncourt_violations"] = strict_oncourt_violations
    report["checks"] = {
        "oncourt_violations": len(oncourt_violations),
        "double_in": len(double_in),
        "double_out": len(double_out),
        "phantom_events": len(phantom_events),
        "unknown_players": len(unknown_players),
        "pairing_errors": len(pairing_errors),
        "clock_backwards": len(clock_backwards),
        "max_seconds_back": max((entry["seconds_back"] for entry in clock_backwards),
                                default=0),
    }
    # Full record of every backwards step, not just the sample, so the season
    # totals can be aggregated exactly rather than estimated.
    report["clock_backwards_sizes"] = [entry["seconds_back"]
                                       for entry in clock_backwards]
    report["clock_backwards_at_substitution"] = sum(
        1 for entry in clock_backwards if entry["is_substitution"])

    clamped = minutes_with_monotonic_clock(box_players, stream, last_period)
    report["clamped_clock_mismatches"] = len(clamped)
    report["clamped_clock_max_abs_delta"] = max((abs(d) for d in clamped), default=0)
    # Keep a bounded sample of each problem so the results file stays readable.
    report["samples"] = {
        "oncourt_violations": oncourt_violations[:10],
        "double_in": double_in[:10],
        "double_out": double_out[:10],
        "phantom_events": phantom_events[:10],
        "unknown_players": unknown_players[:10],
        "clock_backwards": clock_backwards[:10],
    }
    report["phantom_by_playtype"] = dict(phantom_by_playtype)
    report["coach_events"] = dict(coach_events)

    # --- 8. Observations about how overtime is represented ---------------
    extra = pbp.get("ExtraTime") or []
    if extra:
        minutes = [event.get("MINUTE") for event in extra
                   if isinstance(event.get("MINUTE"), int)]
        report["extratime_observation"] = {
            "events": len(extra),
            "begin_period_markers": sum(1 for e in extra if playtype(e) == "BP"),
            "end_period_markers": sum(1 for e in extra if playtype(e) == "EP"),
            "end_game_markers": sum(1 for e in extra if playtype(e) == "EG"),
            "minute_min": min(minutes) if minutes else None,
            "minute_max": max(minutes) if minutes else None,
            "first_playtype": playtype(extra[0]),
            "max_markertime": max(
                (clean(e.get("MARKERTIME")) for e in extra
                 if clean(e.get("MARKERTIME"))), default=None),
        }

    return report


def collect_id_shapes(boxscore, pbp, shapes):
    """Accumulate evidence about player ID formats and space padding."""
    for team_block in boxscore.get("Stats") or []:
        for row in team_block.get("PlayersStats") or []:
            raw = row.get("Player_ID")
            if raw is None:
                continue
            stripped = raw.strip()
            if not stripped:
                continue
            shapes["ids"].add(stripped)
            shapes["raw_lengths"][len(raw)] += 1
            shapes["padded" if raw != stripped else "unpadded"] += 1
            if re.fullmatch(r"P\d{6}", stripped):
                shapes["format_p6"].add(stripped)
            elif re.fullmatch(r"P[A-Z0-9]{3}", stripped):
                shapes["format_legacy4"].add(stripped)
            else:
                shapes["format_other"].add(stripped)
            shapes["name_by_id"].setdefault(stripped, set()).add(
                clean(row.get("Player")))
    for key in PERIOD_LISTS:
        for event in pbp.get(key) or []:
            raw = event.get("PLAYER_ID")
            if raw is None:
                continue
            stripped = raw.strip()
            if not stripped:
                continue
            shapes["pbp_ids"].add(stripped)
            shapes["pbp_raw_lengths"][len(raw)] += 1
            shapes["pbp_padded" if raw != stripped else "pbp_unpadded"] += 1
            if not (re.fullmatch(r"P\d{6}", stripped)
                    or re.fullmatch(r"P[A-Z0-9]{3}", stripped)):
                shapes["format_other"].add(stripped)
            raw_team = event.get("CODETEAM")
            if raw_team is not None and raw_team.strip():
                shapes["team_raw_lengths"][len(raw_team)] += 1


def main():
    schedule_path = os.path.join(CACHE_ROOT, "schedule.json")
    schedule_by_code = {}
    if os.path.exists(schedule_path):
        with open(schedule_path, encoding="utf-8") as handle:
            for game in json.load(handle)["data"]:
                schedule_by_code[game["gameCode"]] = game

    box_codes = {int(os.path.basename(p)[:-5])
                 for p in glob.glob(os.path.join(CACHE_ROOT, "Boxscore", "*.json"))}
    pbp_codes = {int(os.path.basename(p)[:-5])
                 for p in glob.glob(os.path.join(CACHE_ROOT, "PlaybyPlay", "*.json"))}
    gamecodes = sorted(box_codes & pbp_codes)
    print(f"cached: {len(box_codes)} box scores, {len(pbp_codes)} play-by-plays, "
          f"{len(gamecodes)} complete pairs")

    shapes = {
        "ids": set(), "pbp_ids": set(),
        "format_p6": set(), "format_legacy4": set(), "format_other": set(),
        "raw_lengths": collections.Counter(), "pbp_raw_lengths": collections.Counter(),
        "team_raw_lengths": collections.Counter(),
        "padded": 0, "unpadded": 0, "pbp_padded": 0, "pbp_unpadded": 0,
        "name_by_id": {},
    }

    reports = []
    for gamecode in gamecodes:
        with open(os.path.join(CACHE_ROOT, "Boxscore", f"{gamecode}.json"),
                  encoding="utf-8") as handle:
            boxscore = json.load(handle)
        with open(os.path.join(CACHE_ROOT, "PlaybyPlay", f"{gamecode}.json"),
                  encoding="utf-8") as handle:
            pbp = json.load(handle)

        try:
            report = reconstruct_game(gamecode, boxscore, pbp)
        except Exception as exc:  # keep the sweep going, record the crash
            report = {"gamecode": gamecode, "fatal": f"{type(exc).__name__}: {exc}",
                      "checks": {}}
        meta = schedule_by_code.get(gamecode, {})
        report["phase"] = (meta.get("phaseType") or {}).get("name")
        report["round"] = meta.get("round")
        report["played"] = meta.get("played")
        report["game_status"] = meta.get("gameStatus")
        report["venue"] = (meta.get("venue") or {}).get("name")
        report["local"] = ((meta.get("local") or {}).get("club") or {}).get("code")
        report["road"] = ((meta.get("road") or {}).get("club") or {}).get("code")
        report["date"] = meta.get("date")
        schedule_extra = ((meta.get("local") or {}).get("partials") or {}).get(
            "extraPeriods") or {}
        report["schedule_extra_periods"] = len(schedule_extra)
        reports.append(report)

        collect_id_shapes(boxscore, pbp, shapes)

    summary = summarise(reports, shapes)
    with open(RESULTS_PATH, "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "games": reports}, handle, indent=1)
    print(f"\nwrote {RESULTS_PATH}")
    print(json.dumps(summary, indent=1))


def lineup_is_clean(report):
    """Do the hard lineup invariants hold exactly?

    These are the invariants CLAUDE.md commits to: five players on court at all
    times, every IN matched by an OUT, minutes reconciling with the official box
    score to the second, and team totals of 200 minutes per regulation game plus
    25 per overtime. If these hold, the reconstructed lineup is trustworthy.
    """
    if report.get("fatal"):
        return False
    checks = report.get("checks", {})
    if not report.get("starters_ok"):
        return False
    for key in ("oncourt_violations", "double_in", "double_out",
                "unknown_players", "pairing_errors"):
        if checks.get(key):
            return False
    if report.get("players_with_delta"):
        return False
    for totals in (report.get("team_totals") or {}).values():
        if totals["delta_seconds"] != 0:
            return False
    return True


def is_clean(report):
    """Hard invariants hold AND no event is credited to an off-court player.

    Stricter than lineup_is_clean. The extra condition is an event-ordering
    check rather than a lineup check: a row sitting a few positions too late in
    the stream trips it without the lineup itself being wrong.
    """
    if not lineup_is_clean(report):
        return False
    return not report.get("checks", {}).get("phantom_events")


def summarise(reports, shapes):
    total = len(reports)
    clean_games = [r for r in reports if is_clean(r)]
    lineup_clean = [r for r in reports if lineup_is_clean(r)]
    failures = [r for r in reports if not is_clean(r)]
    counter = collections.Counter()
    for report in failures:
        checks = report.get("checks", {})
        if report.get("fatal"):
            counter["fatal"] += 1
        if not report.get("starters_ok"):
            counter["bad_starter_count"] += 1
        for key in ("oncourt_violations", "double_in", "double_out",
                    "phantom_events", "unknown_players", "pairing_errors"):
            if checks.get(key):
                counter[key] += 1
        if report.get("players_with_delta"):
            counter["minute_mismatch"] += 1
        for totals in (report.get("team_totals") or {}).values():
            if totals["delta_seconds"] != 0:
                counter["team_total_mismatch"] += 1
                break

    overtime_games = [r for r in reports if r.get("overtime_periods")]

    phantom_types = collections.Counter()
    phantom_total = 0
    phantom_same_clock = 0
    phantom_sampled = 0
    for report in reports:
        for key, value in (report.get("phantom_by_playtype") or {}).items():
            phantom_types[key] += value
            phantom_total += value
        for sample in (report.get("samples", {}) or {}).get("phantom_events", []):
            phantom_sampled += 1
            if sample.get("same_clock_as_out"):
                phantom_same_clock += 1

    coach_types = collections.Counter()
    for report in reports:
        for key, value in (report.get("coach_events") or {}).items():
            coach_types[key] += value

    # Do the failures cluster anywhere? Compare each attribute's share of the
    # failures against its share of all games, so a busy venue does not look
    # guilty just because it hosts a lot of basketball.
    def clustering(attribute):
        all_games = collections.Counter(r.get(attribute) for r in reports)
        failed = collections.Counter(r.get(attribute) for r in failures)
        return {str(key): {"failed": count, "played": all_games[key]}
                for key, count in failed.most_common()}

    failure_patterns = {
        "by_phase": clustering("phase"),
        "by_venue": clustering("venue"),
        "by_round": clustering("round"),
        "by_overtime": clustering("overtime_periods"),
        "teams_involved": dict(collections.Counter(
            team for r in failures for team in (r.get("teams") or [])).most_common()),
        "failing_gamecodes": [r["gamecode"] for r in failures],
    }

    return {
        "games_analysed": total,
        "clean_games": len(clean_games),
        "clean_percentage": round(100.0 * len(clean_games) / total, 2) if total else 0,
        "lineup_clean_games": len(lineup_clean),
        "lineup_clean_percentage": (round(100.0 * len(lineup_clean) / total, 2)
                                    if total else 0),
        "failing_games": len(failures),
        "failure_reasons": dict(counter),
        "failure_patterns": failure_patterns,
        "overtime_games": len(overtime_games),
        # Independent check: the schedule endpoint publishes an extraPeriods
        # block per game, so the overtime count inferred from the event stream
        # can be verified against a source that never saw the event stream.
        "overtime_matches_schedule": sum(
            1 for r in reports
            if r.get("overtime_periods") == r.get("schedule_extra_periods")),
        "overtime_disagreements": [
            {"gamecode": r["gamecode"], "from_events": r.get("overtime_periods"),
             "from_schedule": r.get("schedule_extra_periods")}
            for r in reports
            if r.get("overtime_periods") != r.get("schedule_extra_periods")],
        "overtime_distribution": dict(collections.Counter(
            r.get("overtime_periods", 0) for r in reports)),
        "phantom_events_total": phantom_total,
        "phantom_events_by_playtype": dict(phantom_types),
        "games_with_phantom_events": sum(
            1 for r in reports if r.get("checks", {}).get("phantom_events")),
        "phantom_sampled": phantom_sampled,
        "phantom_sharing_clock_with_their_own_sub_out": phantom_same_clock,
        "coach_events_by_playtype": dict(coach_types),
        "games_with_clock_backwards": sum(
            1 for r in reports if r.get("checks", {}).get("clock_backwards")),
        "max_seconds_back_any_game": max(
            (r.get("checks", {}).get("max_seconds_back", 0) for r in reports),
            default=0),
        "clock_backwards_total": sum(
            len(r.get("clock_backwards_sizes") or []) for r in reports),
        "clock_backwards_size_histogram": dict(sorted(collections.Counter(
            size for r in reports
            for size in (r.get("clock_backwards_sizes") or [])).items())),
        "clock_backwards_at_substitution": sum(
            r.get("clock_backwards_at_substitution", 0) for r in reports),
        "clamped_clock_games_with_mismatch": sum(
            1 for r in reports if r.get("clamped_clock_mismatches")),
        "clamped_clock_player_mismatches": sum(
            r.get("clamped_clock_mismatches", 0) for r in reports),
        "clamped_clock_max_abs_delta": max(
            (r.get("clamped_clock_max_abs_delta", 0) for r in reports), default=0),
        "max_abs_minute_delta_any_game": max(
            (r.get("max_abs_minute_delta", 0) for r in reports), default=0),
        "id_shapes": {
            "distinct_box_ids": len(shapes["ids"]),
            "distinct_pbp_ids": len(shapes["pbp_ids"]),
            "format_p_plus_6_digits": len(shapes["format_p6"]),
            "format_legacy_4_char": len(shapes["format_legacy4"]),
            "format_other": sorted(shapes["format_other"])[:20],
            "format_other_count": len(shapes["format_other"]),
            "box_raw_length_histogram": dict(shapes["raw_lengths"]),
            "pbp_raw_length_histogram": dict(shapes["pbp_raw_lengths"]),
            "team_code_raw_length_histogram": dict(shapes["team_raw_lengths"]),
            "box_padded_fields": shapes["padded"],
            "box_unpadded_fields": shapes["unpadded"],
            "pbp_padded_fields": shapes["pbp_padded"],
            "pbp_unpadded_fields": shapes["pbp_unpadded"],
            "ids_with_multiple_names": sum(
                1 for names in shapes["name_by_id"].values() if len(names) > 1),
        },
    }


if __name__ == "__main__":
    main()
