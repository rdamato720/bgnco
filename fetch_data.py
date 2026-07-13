#!/usr/bin/env python3
"""
Pulls your entire ESPN league history, works out who is actually who across
twenty years of account changes, and computes all-time records, Elo power
ratings, luck, head-to-head history, and this week's projected winners.

Writes site/data/league.json, which the static site reads.

Usage:
    python3 fetch_data.py                  # uses config.py
    python3 fetch_data.py --league 123456  # override league id
"""

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from espn_api.football import League
from espn_api.football.team import Team as _Team

import identity
import lore

# ESPN's oldest seasons store player records in a shape the library can't parse,
# which crashes roster building and would lose the whole year. We never use
# rosters, so skip them when they blow up rather than losing the season.
_orig_roster = _Team._fetch_roster


def _safe_roster(self, data, year, pro_schedule=None):
    try:
        _orig_roster(self, data, year, pro_schedule)
    except Exception:
        self.roster = []


_Team._fetch_roster = _safe_roster

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "site", "data", "league.json")

ELO_START = 1500.0
ELO_K = 24.0            # how much one game moves a rating
ELO_REGRESSION = 0.30   # fraction pulled back to 1500 between seasons
BLEND_ESPN = 0.60       # ESPN's projection vs. Elo, when computing win probability


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Elo
# ---------------------------------------------------------------------------

def elo_expected(a, b):
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


def elo_update(a, b, score_a, score_b, k=ELO_K):
    """Margin-aware. Blowouts move ratings more than squeakers, but not linearly."""
    actual = 0.5 if score_a == score_b else (1.0 if score_a > score_b else 0.0)
    expected = elo_expected(a, b)
    margin = abs(score_a - score_b)
    mult = math.log(max(margin, 1.0) + 1.0) / math.log(30.0)
    mult = min(max(mult, 0.5), 1.8)
    delta = k * mult * (actual - expected)
    return a + delta, b - delta


def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def discover_seasons(league_id, espn_s2, swid, probe_year):
    for year in (probe_year, probe_year - 1):
        try:
            lg = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
            prev = sorted(set(getattr(lg, "previousSeasons", []) or []))
            seasons = sorted(set(prev + [year]))
            log(f"  ESPN reports seasons: {seasons[0]}-{seasons[-1]} ({len(seasons)} total)")
            return seasons
        except Exception as e:
            log(f"  {year} not available yet ({type(e).__name__}). Trying earlier.")
    raise SystemExit(
        "Could not reach the league. Check the league ID, and if the league is private "
        "make sure ESPN_S2 and SWID are set in config.py."
    )


def pull_all(league_id, espn_s2, swid, seasons):
    raw, incomplete = {}, []
    for year in seasons:
        try:
            lg = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
        except Exception as e:
            log(f"  {year}: unavailable ({type(e).__name__})")
            incomplete.append({"year": year, "reason": f"ESPN returned nothing ({type(e).__name__})"})
            continue
        if not lg.teams:
            log(f"  {year}: no teams returned")
            incomplete.append({"year": year, "reason": "no team data"})
            continue
        raw[year] = lg
        weeks = max((len(getattr(t, "scores", []) or []) for t in lg.teams), default=0)
        log(f"  {year}: {len(lg.teams)} teams, {weeks} weeks")
        time.sleep(0.35)
    return raw, incomplete


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(league_id, espn_s2, swid, probe_year):
    log(f"Reading league {league_id} ...")
    seasons = discover_seasons(league_id, espn_s2, swid, probe_year)
    raw, incomplete = pull_all(league_id, espn_s2, swid, seasons)
    if not raw:
        raise SystemExit("No seasons could be read.")

    # ---- pass 1: figure out who is actually who -----------------------------
    ident = identity.Identity()
    for year, lg in raw.items():
        for t in lg.teams:
            ident.observe(t, year)
    ident.resolve()
    ident.report(log)

    # ---- pass 2: compute everything ----------------------------------------
    fr = {}

    def get(fid):
        if fid not in fr:
            fr[fid] = {
                "id": fid, "manager": ident.display(fid), "team_name": "",
                "aliases": [], "first_season": 9999, "last_season": 0, "seasons": 0,
                "wins": 0, "losses": 0, "ties": 0,
                "points_for": 0.0, "points_against": 0.0, "games": 0,
                "championships": [], "runner_ups": [], "playoff_appearances": 0,
                "finishes": [], "elo": ELO_START, "elo_peak": ELO_START, "logo": "",
            }
        return fr[fid]

    season_payload = []
    h2h = defaultdict(lambda: defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0}))
    all_margins = []
    elo_by_season = defaultdict(list)
    records = {k: None for k in ("highest_score", "lowest_score", "biggest_blowout",
                                 "closest_game", "highest_combined", "best_regular_season")}

    for year in sorted(raw):
        lg = raw[year]

        for r in fr.values():
            r["elo"] = ELO_START + (r["elo"] - ELO_START) * (1 - ELO_REGRESSION)

        tid_to_fid = {}
        for t in lg.teams:
            fid = ident.franchise_id(year, t.team_id)
            tid_to_fid[t.team_id] = fid
            r = get(fid)
            r["team_name"] = t.team_name
            r["first_season"] = min(r["first_season"], year)
            r["last_season"] = max(r["last_season"], year)
            if t.team_name not in r["aliases"]:
                r["aliases"].append(t.team_name)
            if getattr(t, "logo_url", ""):
                r["logo"] = t.logo_url

        reg = getattr(lg.settings, "reg_season_count", 14) or 14
        max_week = max((len(getattr(t, "scores", []) or []) for t in lg.teams), default=0)

        weeks_out, has_scores, seen = [], False, set()
        for w in range(1, max_week + 1):
            matchups = []
            for t in lg.teams:
                sched = getattr(t, "schedule", []) or []
                scores = getattr(t, "scores", []) or []
                if w > len(sched) or w > len(scores):
                    continue
                opp = sched[w - 1]
                if not hasattr(opp, "team_id"):
                    continue
                key = (w, tuple(sorted([t.team_id, opp.team_id])))
                if key in seen:
                    continue
                seen.add(key)
                opp_scores = getattr(opp, "scores", []) or []
                if w > len(opp_scores):
                    continue

                a_sc = round(float(scores[w - 1]), 2)
                b_sc = round(float(opp_scores[w - 1]), 2)
                if a_sc == 0 and b_sc == 0:
                    continue
                fa, fb = tid_to_fid[t.team_id], tid_to_fid[opp.team_id]
                if fa == fb:
                    continue   # nobody plays themselves; guards a bad merge
                has_scores = True

                matchups.append({"week": w, "playoff": w > reg, "a": fa, "b": fb,
                                 "a_score": a_sc, "b_score": b_sc})

                for me, them, ms, ts in ((fa, fb, a_sc, b_sc), (fb, fa, b_sc, a_sc)):
                    r = get(me)
                    r["points_for"] += ms
                    r["points_against"] += ts
                    r["games"] += 1
                    if ms > ts:
                        r["wins"] += 1; h2h[me][them]["w"] += 1
                    elif ms < ts:
                        r["losses"] += 1; h2h[me][them]["l"] += 1
                    else:
                        r["ties"] += 1; h2h[me][them]["t"] += 1
                    h2h[me][them]["pf"] += ms
                    h2h[me][them]["pa"] += ts

                margin = abs(a_sc - b_sc)
                all_margins.append(margin)

                for who, sc, opp_fid, osc in ((fa, a_sc, fb, b_sc), (fb, b_sc, fa, a_sc)):
                    ctx = {"franchise": who, "opponent": opp_fid, "score": sc,
                           "opp_score": osc, "year": year, "week": w}
                    if records["highest_score"] is None or sc > records["highest_score"]["score"]:
                        records["highest_score"] = ctx
                    if records["lowest_score"] is None or sc < records["lowest_score"]["score"]:
                        records["lowest_score"] = ctx

                blow = {"winner": fa if a_sc > b_sc else fb,
                        "loser": fb if a_sc > b_sc else fa,
                        "margin": round(margin, 2),
                        "score": f"{max(a_sc, b_sc)} - {min(a_sc, b_sc)}",
                        "year": year, "week": w}
                if records["biggest_blowout"] is None or margin > records["biggest_blowout"]["margin"]:
                    records["biggest_blowout"] = blow
                if margin > 0 and (records["closest_game"] is None
                                   or margin < records["closest_game"]["margin"]):
                    records["closest_game"] = blow

                combined = round(a_sc + b_sc, 2)
                if records["highest_combined"] is None or combined > records["highest_combined"]["total"]:
                    records["highest_combined"] = {"a": fa, "b": fb, "total": combined,
                                                   "score": f"{a_sc} - {b_sc}", "year": year, "week": w}

                ra, rb = get(fa)["elo"], get(fb)["elo"]
                na, nb = elo_update(ra, rb, a_sc, b_sc)
                get(fa)["elo"], get(fb)["elo"] = na, nb
                for f, v in ((fa, na), (fb, nb)):
                    get(f)["elo_peak"] = max(get(f)["elo_peak"], v)

            if matchups:
                weeks_out.append({"week": w, "playoff": w > reg, "matchups": matchups})

        try:
            standings = lg.standings()
        except Exception:
            standings = sorted(lg.teams, key=lambda x: (-x.wins, -x.points_for))

        champion = runner_up = None
        season_teams = []
        for place, t in enumerate(standings, start=1):
            fid = tid_to_fid[t.team_id]
            final = getattr(t, "final_standing", 0) or place
            season_teams.append({
                "franchise": fid, "team_name": t.team_name,
                "wins": t.wins, "losses": t.losses, "ties": t.ties,
                "points_for": round(float(t.points_for), 2),
                "points_against": round(float(t.points_against), 2),
                "seed": getattr(t, "standing", 0), "final": final,
            })
            if has_scores:
                get(fid)["finishes"].append(final)
                if final == 1:
                    champion = fid
                    get(fid)["championships"].append(year)
                elif final == 2:
                    runner_up = fid
                    get(fid)["runner_ups"].append(year)
                if getattr(t, "standing", 99) <= (getattr(lg.settings, "playoff_team_count", 6) or 6):
                    get(fid)["playoff_appearances"] += 1

        if has_scores:
            for fid in set(tid_to_fid.values()):
                get(fid)["seasons"] += 1
                elo_by_season[fid].append({"year": year, "elo": round(get(fid)["elo"], 1)})
        else:
            incomplete.append({"year": year, "reason": "standings only, no weekly scores"})

        for st in season_teams:
            gp = st["wins"] + st["losses"] + st["ties"]
            if gp >= 8:
                p = (st["wins"] + 0.5 * st["ties"]) / gp
                cur = records["best_regular_season"]
                if cur is None or p > cur["pct"] or (p == cur["pct"] and st["points_for"] > cur["points_for"]):
                    records["best_regular_season"] = {
                        "franchise": st["franchise"], "year": year,
                        "record": f'{st["wins"]}-{st["losses"]}' + (f'-{st["ties"]}' if st["ties"] else ""),
                        "pct": p, "points_for": st["points_for"],
                    }

        season_payload.append({
            "year": year, "name": getattr(lg.settings, "name", ""),
            "team_count": len(lg.teams), "reg_season_weeks": reg,
            "champion": champion, "runner_up": runner_up,
            "standings": season_teams, "weeks": weeks_out, "complete": has_scores,
        })

    sigma = max(statistics.pstdev(all_margins) if len(all_margins) > 5 else 28.0, 10.0)

    h2h_plain = {a: dict(b) for a, b in h2h.items()}
    extras = lore.compute_all(season_payload, h2h_plain)
    luck, strk = extras["luck"], extras["streaks"]

    latest_complete = max((s["year"] for s in season_payload if s["complete"]),
                          default=season_payload[-1]["year"])
    active = set()
    for s in season_payload:
        if s["year"] >= latest_complete:
            active.update(t["franchise"] for t in s["standings"])

    current = build_current(raw, ident, fr, sigma, sorted(raw)[-1])

    franchises = []
    for r in fr.values():
        gp = max(r["games"], 1)
        fs = r["finishes"]
        lk = luck.get(r["id"], {})
        st = strk.get(r["id"], {})
        franchises.append({
            **r,
            "active": r["id"] in active,
            "elo": round(r["elo"], 1), "elo_peak": round(r["elo_peak"], 1),
            "points_for": round(r["points_for"], 2),
            "points_against": round(r["points_against"], 2),
            "ppg": round(r["points_for"] / gp, 2),
            "papg": round(r["points_against"] / gp, 2),
            "win_pct": round((r["wins"] + 0.5 * r["ties"]) / gp, 4) if r["games"] else 0,
            "titles": len(r["championships"]),
            "avg_finish": round(sum(fs) / len(fs), 2) if fs else None,
            "best_finish": min(fs) if fs else None,
            "all_play": lk.get("all_play"),
            "all_play_pct": lk.get("all_play_pct"),
            "expected_wins": lk.get("expected_wins"),
            "luck": lk.get("luck"),
            "luck_per_season": lk.get("luck_per_season", []),
            "best_win_streak": (st.get("win") or {}).get("n", 0),
            "worst_loss_streak": (st.get("loss") or {}).get("n", 0),
            "streak_detail": st,
        })
    franchises.sort(key=lambda f: (-f["titles"], -f["win_pct"], -f["points_for"]))

    _, _, suspects = ident.resolve()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "league": {
            "id": league_id,
            "name": season_payload[-1]["name"] or f"League {league_id}",
            "seasons": [s["year"] for s in season_payload],
            "first_season": season_payload[0]["year"],
            "latest_season": season_payload[-1]["year"],
            "years": len(season_payload),
        },
        "model": {"elo_k": ELO_K, "regression": ELO_REGRESSION,
                  "margin_sigma": round(sigma, 2), "espn_weight": BLEND_ESPN},
        "franchises": franchises,
        "seasons": season_payload,
        "head_to_head": h2h_plain,
        "records": records,
        "elo_by_season": dict(elo_by_season),
        "trophy_case": extras["trophy_case"],
        "top_weeks": extras["top_weeks"],
        "rivalries": extras["rivalries"],
        "total_games": extras["total_games"],
        "current": current,
        "incomplete": incomplete,
        "suspected_duplicates": suspects,
    }


def build_current(raw, ident, fr, sigma, year):
    lg = raw.get(year)
    if lg is None:
        return {"state": "offseason", "year": year, "week": None, "matchups": [],
                "standings": [], "power": [],
                "note": "The current season is not open on ESPN yet."}

    tid_to_fid = {t.team_id: ident.franchise_id(year, t.team_id) for t in lg.teams}
    week = getattr(lg, "current_week", 1) or 1
    reg = getattr(lg.settings, "reg_season_count", 14) or 14
    played = any(any(s for s in (getattr(t, "scores", []) or [])) for t in lg.teams)
    state = "regular_season" if played else "preseason"
    if played and week > reg:
        state = "playoffs"

    def elo(fid):
        return fr[fid]["elo"] if fid in fr else ELO_START

    def wprob(fa, fb, pa, pb):
        p_elo = elo_expected(elo(fa), elo(fb))
        if pa is None or pb is None or (pa == 0 and pb == 0):
            return p_elo
        return BLEND_ESPN * normal_cdf((pa - pb) / sigma) + (1 - BLEND_ESPN) * p_elo

    matchups, box = [], []
    try:
        box = lg.box_scores(week)
    except Exception:
        log(f"  box scores for week {week} unavailable (normal in the offseason)")

    if box:
        for b in box:
            if not b.home_team or not b.away_team:
                continue
            hid = getattr(b.home_team, "team_id", b.home_team)
            aid = getattr(b.away_team, "team_id", b.away_team)
            fh, fa = tid_to_fid.get(hid), tid_to_fid.get(aid)
            if not fh or not fa:
                continue
            ph = round(float(b.home_projected or 0), 1)
            pa_ = round(float(b.away_projected or 0), 1)
            wp = wprob(fh, fa, ph, pa_)
            matchups.append({"home": fh, "away": fa, "home_proj": ph, "away_proj": pa_,
                             "home_score": round(float(b.home_score or 0), 2),
                             "away_score": round(float(b.away_score or 0), 2),
                             "home_wp": round(wp, 3), "away_wp": round(1 - wp, 3),
                             "playoff": bool(getattr(b, "is_playoff", False))})
    else:
        seen = set()
        for t in lg.teams:
            sched = getattr(t, "schedule", []) or []
            if week > len(sched):
                continue
            opp = sched[week - 1]
            if not hasattr(opp, "team_id"):
                continue
            k = tuple(sorted([t.team_id, opp.team_id]))
            if k in seen:
                continue
            seen.add(k)
            fh, fa = tid_to_fid.get(t.team_id), tid_to_fid.get(opp.team_id)
            if not fh or not fa or fh == fa:
                continue
            wp = wprob(fh, fa, None, None)
            matchups.append({"home": fh, "away": fa, "home_proj": None, "away_proj": None,
                             "home_score": 0, "away_score": 0,
                             "home_wp": round(wp, 3), "away_wp": round(1 - wp, 3),
                             "playoff": False})

    standings = []
    try:
        for place, t in enumerate(lg.standings(), start=1):
            standings.append({
                "franchise": tid_to_fid[t.team_id], "team_name": t.team_name,
                "wins": t.wins, "losses": t.losses, "ties": t.ties,
                "points_for": round(float(t.points_for), 2),
                "points_against": round(float(t.points_against), 2),
                "place": place,
            })
    except Exception:
        pass

    power = sorted([{"franchise": f, "elo": round(elo(f), 1)} for f in set(tid_to_fid.values())],
                   key=lambda x: -x["elo"])
    for i, p in enumerate(power, 1):
        p["rank"] = i

    note = None
    if state == "preseason":
        note = f"The {year} season has not kicked off. These are seeded from all-time rating only."

    return {"state": state, "year": year, "week": week, "reg_season_weeks": reg,
            "matchups": matchups, "standings": standings, "power": power, "note": note}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", type=int, default=None)
    ap.add_argument("--year", type=int, default=None)
    args = ap.parse_args()

    league_id = args.league or int(os.environ.get("LEAGUE_ID", 0)) or None
    espn_s2 = os.environ.get("ESPN_S2") or None
    swid = os.environ.get("SWID") or None

    if league_id is None:
        try:
            import config
            league_id = config.LEAGUE_ID
            espn_s2 = espn_s2 or getattr(config, "ESPN_S2", None)
            swid = swid or getattr(config, "SWID", None)
        except ImportError:
            raise SystemExit(
                "No league ID. Copy config.example.py to config.py and fill it in, "
                "or run: python3 fetch_data.py --league YOUR_LEAGUE_ID"
            )

    payload = build(league_id, espn_s2, swid, args.year or datetime.now().year)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    L = payload["league"]
    log("")
    log(f"Wrote {OUT_PATH}  ({os.path.getsize(OUT_PATH)/1024:.0f} KB)")
    log(f"  {L['name']}")
    log(f"  {L['years']} seasons, {L['first_season']}-{L['latest_season']}")
    log(f"  {len(payload['franchises'])} franchises, {payload['total_games']:,} games")
    if payload["incomplete"]:
        log("")
        log("  Partial seasons:")
        for i in payload["incomplete"]:
            log(f"    {i['year']}: {i['reason']}")


if __name__ == "__main__":
    main()
