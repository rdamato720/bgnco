"""
Derived league lore. Everything here is computed from the season data that
fetch_data.py already pulled, so it needs no extra ESPN calls.
"""

from collections import defaultdict


def chronological_games(seasons):
    """Every game ever played, in the order it happened."""
    out = []
    for s in sorted(seasons, key=lambda x: x["year"]):
        for w in sorted(s["weeks"], key=lambda x: x["week"]):
            for m in w["matchups"]:
                out.append({
                    "year": s["year"], "week": w["week"], "playoff": w["playoff"],
                    "a": m["a"], "b": m["b"],
                    "a_score": m["a_score"], "b_score": m["b_score"],
                })
    return out


# ---------------------------------------------------------------------------
# The Championship Belt
#
# Boxing rules. The winner of the first game in league history takes the belt.
# It only changes hands when the holder loses. If the holder isn't playing that
# week, the belt sits. Ties keep the belt with the holder.
# ---------------------------------------------------------------------------

def championship_belt(games):
    if not games:
        return {"holder": None, "reigns": [], "leaderboard": []}

    holder = None
    reigns = []          # [{holder, from, to, defenses, lost_to}]
    cur = None

    for g in games:
        if holder is None:
            # First game ever. Winner is crowned.
            if g["a_score"] == g["b_score"]:
                continue
            holder = g["a"] if g["a_score"] > g["b_score"] else g["b"]
            cur = {"holder": holder, "from": {"year": g["year"], "week": g["week"]},
                   "to": None, "defenses": 0, "lost_to": None, "won_from": None}
            continue

        if holder not in (g["a"], g["b"]):
            continue  # holder idle, belt sits

        if g["a"] == holder:
            mine, theirs, challenger = g["a_score"], g["b_score"], g["b"]
        else:
            mine, theirs, challenger = g["b_score"], g["a_score"], g["a"]

        if mine >= theirs:
            cur["defenses"] += 1
        else:
            cur["to"] = {"year": g["year"], "week": g["week"]}
            cur["lost_to"] = challenger
            reigns.append(cur)
            holder = challenger
            cur = {"holder": holder, "from": {"year": g["year"], "week": g["week"]},
                   "to": None, "defenses": 0, "lost_to": None, "won_from": reigns[-1]["holder"]}

    if cur:
        reigns.append(cur)

    # Who has held it the longest, in total games defended?
    tally = defaultdict(lambda: {"reigns": 0, "defenses": 0, "longest": 0})
    for r in reigns:
        t = tally[r["holder"]]
        t["reigns"] += 1
        t["defenses"] += r["defenses"]
        t["longest"] = max(t["longest"], r["defenses"])
    leaderboard = sorted(
        [{"franchise": f, **v} for f, v in tally.items()],
        key=lambda x: (-x["defenses"], -x["longest"]),
    )

    return {"holder": holder, "reigns": reigns, "leaderboard": leaderboard}


# ---------------------------------------------------------------------------
# Luck: what your record would be if the schedule were fair
#
# Each week, compare every team's score against every other team's score that
# week. That "all-play" record is schedule-independent. Expected wins is the
# all-play win rate scaled to games actually played. Actual minus expected is
# luck, and over twenty years it is remarkably revealing.
# ---------------------------------------------------------------------------

def luck_and_all_play(seasons):
    ap = defaultdict(lambda: {"w": 0, "l": 0, "t": 0})
    exp_w = defaultdict(float)
    act_w = defaultdict(float)
    games = defaultdict(int)
    per_season = defaultdict(list)   # fid -> [{year, actual, expected, luck}]

    for s in seasons:
        s_exp = defaultdict(float)
        s_act = defaultdict(float)
        s_gp = defaultdict(int)

        for w in s["weeks"]:
            scores = {}
            for m in w["matchups"]:
                scores[m["a"]] = m["a_score"]
                scores[m["b"]] = m["b_score"]
            if len(scores) < 2:
                continue

            for fid, sc in scores.items():
                beat = tied = 0
                for other, osc in scores.items():
                    if other == fid:
                        continue
                    if sc > osc:
                        beat += 1
                    elif sc == osc:
                        tied += 1
                lost = (len(scores) - 1) - beat - tied
                ap[fid]["w"] += beat
                ap[fid]["l"] += lost
                ap[fid]["t"] += tied
                field = len(scores) - 1
                if field:
                    e = (beat + 0.5 * tied) / field
                    exp_w[fid] += e
                    s_exp[fid] += e
                games[fid] += 1
                s_gp[fid] += 1

            for m in w["matchups"]:
                if m["a_score"] > m["b_score"]:
                    act_w[m["a"]] += 1; s_act[m["a"]] += 1
                elif m["b_score"] > m["a_score"]:
                    act_w[m["b"]] += 1; s_act[m["b"]] += 1
                else:
                    act_w[m["a"]] += 0.5; act_w[m["b"]] += 0.5
                    s_act[m["a"]] += 0.5; s_act[m["b"]] += 0.5

        for fid in s_gp:
            per_season[fid].append({
                "year": s["year"],
                "actual": round(s_act[fid], 1),
                "expected": round(s_exp[fid], 1),
                "luck": round(s_act[fid] - s_exp[fid], 1),
                "games": s_gp[fid],
            })

    out = {}
    for fid in games:
        out[fid] = {
            "all_play": ap[fid],
            "all_play_pct": round(
                (ap[fid]["w"] + 0.5 * ap[fid]["t"]) /
                max(ap[fid]["w"] + ap[fid]["l"] + ap[fid]["t"], 1), 4),
            "expected_wins": round(exp_w[fid], 1),
            "actual_wins": round(act_w[fid], 1),
            "luck": round(act_w[fid] - exp_w[fid], 1),
            "luck_per_season": per_season[fid],
        }
    return out


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

def streaks(games):
    cur = defaultdict(lambda: {"type": None, "n": 0, "start": None})
    best = {}   # fid -> {"win": {...}, "loss": {...}}

    def note(fid, kind, run, start, end):
        b = best.setdefault(fid, {"win": None, "loss": None})
        if b[kind] is None or run > b[kind]["n"]:
            b[kind] = {"n": run, "from": start, "to": end}

    for g in games:
        for fid, mine, theirs in ((g["a"], g["a_score"], g["b_score"]),
                                  (g["b"], g["b_score"], g["a_score"])):
            if mine == theirs:
                kind = None
            else:
                kind = "win" if mine > theirs else "loss"
            c = cur[fid]
            here = {"year": g["year"], "week": g["week"]}
            if kind is None:
                if c["type"]:
                    note(fid, c["type"], c["n"], c["start"], here)
                c.update({"type": None, "n": 0, "start": None})
            elif c["type"] == kind:
                c["n"] += 1
            else:
                if c["type"]:
                    note(fid, c["type"], c["n"], c["start"], here)
                c.update({"type": kind, "n": 1, "start": here})

    for fid, c in cur.items():
        if c["type"]:
            note(fid, c["type"], c["n"], c["start"], c["start"])
    return best


# ---------------------------------------------------------------------------
# Top single weeks, ever
# ---------------------------------------------------------------------------

def top_weeks(games, n=25):
    rows = []
    for g in games:
        rows.append({"franchise": g["a"], "score": g["a_score"], "opponent": g["b"],
                     "opp_score": g["b_score"], "year": g["year"], "week": g["week"],
                     "playoff": g["playoff"]})
        rows.append({"franchise": g["b"], "score": g["b_score"], "opponent": g["a"],
                     "opp_score": g["a_score"], "year": g["year"], "week": g["week"],
                     "playoff": g["playoff"]})
    hi = sorted(rows, key=lambda r: -r["score"])[:n]
    lo = sorted(rows, key=lambda r: r["score"])[:n]
    return {"best": hi, "worst": lo}


# ---------------------------------------------------------------------------
# Rivalries: the series worth caring about
# ---------------------------------------------------------------------------

def rivalries(h2h, min_games=8):
    pairs = []
    seen = set()
    for a, opps in h2h.items():
        for b, r in opps.items():
            key = tuple(sorted([a, b]))
            if key in seen:
                continue
            seen.add(key)
            back = h2h.get(b, {}).get(a, {"w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0})
            g = r["w"] + r["l"] + r["t"]
            if g < min_games:
                continue
            pct = (r["w"] + 0.5 * r["t"]) / g
            pairs.append({
                "a": a, "b": b, "games": g,
                "a_wins": r["w"], "b_wins": back["w"], "ties": r["t"],
                "a_pf": round(r["pf"], 1), "b_pf": round(back["pf"], 1),
                "balance": abs(pct - 0.5),
                "total_points": round(r["pf"] + r["pa"], 1),
            })

    return {
        "deadlocked": sorted(pairs, key=lambda p: (p["balance"], -p["games"]))[:6],
        "lopsided": sorted(pairs, key=lambda p: (-p["balance"], -p["games"]))[:6],
        "most_played": sorted(pairs, key=lambda p: -p["games"])[:6],
    }


# ---------------------------------------------------------------------------

def compute_all(seasons, h2h):
    games = chronological_games(seasons)
    return {
        "trophy_case": trophy_case(seasons),
        "luck": luck_and_all_play(seasons),
        "streaks": streaks(games),
        "top_weeks": top_weeks(games),
        "rivalries": rivalries(h2h),
        "total_games": len(games),
    }


# ---------------------------------------------------------------------------
# The Trophy Case
#
# Two pieces of hardware per season:
#   - the championship, decided in the playoffs
#   - the scoring crown, for the most REGULAR SEASON points
#
# Regular season only, because playoff teams play extra games and it would not
# be a fair comparison otherwise. Winning both in one year is the double, and
# it is rare.
# ---------------------------------------------------------------------------

def trophy_case(seasons):
    years = []
    tally = defaultdict(lambda: {
        "titles": [], "runner_ups": [], "crowns": [], "doubles": [],
    })

    for s in sorted(seasons, key=lambda x: x["year"]):
        if not s.get("complete"):
            continue

        # everyone who ever played gets a shelf, even if it stays empty
        for t in s.get("standings", []):
            tally[t["franchise"]]

        pts = defaultdict(float)
        gp = defaultdict(int)
        for w in s["weeks"]:
            if w["playoff"]:
                continue
            for m in w["matchups"]:
                pts[m["a"]] += m["a_score"]
                pts[m["b"]] += m["b_score"]
                gp[m["a"]] += 1
                gp[m["b"]] += 1
        if not pts:
            continue

        board = sorted(pts.items(), key=lambda kv: -kv[1])
        crown_fid, crown_pts = board[0]
        runner_pts = board[1][1] if len(board) > 1 else crown_pts

        champ = s.get("champion")
        ru = s.get("runner_up")
        double = champ is not None and champ == crown_fid

        years.append({
            "year": s["year"],
            "champion": champ,
            "runner_up": ru,
            "crown": crown_fid,
            "crown_points": round(crown_pts, 1),
            "crown_ppg": round(crown_pts / max(gp[crown_fid], 1), 1),
            "crown_margin": round(crown_pts - runner_pts, 1),
            "crown_runner_up": board[1][0] if len(board) > 1 else None,
            "double": double,
            "champion_points": round(pts.get(champ, 0), 1) if champ else None,
            "champion_rank": next((i + 1 for i, (f, _) in enumerate(board) if f == champ), None),
        })

        if champ:
            tally[champ]["titles"].append(s["year"])
        if ru:
            tally[ru]["runner_ups"].append(s["year"])
        tally[crown_fid]["crowns"].append(s["year"])
        if double:
            tally[champ]["doubles"].append(s["year"])

    cabinet = sorted(
        [{"franchise": f, **v,
          "hardware": len(v["titles"]) * 2 + len(v["crowns"])}
         for f, v in tally.items()],
        key=lambda x: (-len(x["titles"]), -len(x["crowns"]), -len(x["runner_ups"])),
    )

    return {"years": list(reversed(years)), "cabinet": cabinet}
