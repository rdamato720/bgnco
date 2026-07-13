# League Record Book

A static site for a long-running ESPN fantasy football league. Pulls every season
ESPN will give you, computes all-time records, Elo power ratings, a full head-to-head
matrix, and projected winners for the current week.

Right now it's loaded with **sample data** so you can see it working. Swap in your
league in about two minutes.

---

## 1. Point it at your league

Find your league ID in the ESPN URL:

```
https://fantasy.espn.com/football/league?leagueId=123456
                                                  ^^^^^^
```

Then:

```bash
pip install -r requirements.txt
python fetch_data.py --league 123456
```

That overwrites `site/data/league.json` with your real history. The script prints a
summary of what it found, including any seasons ESPN couldn't fully return.

If you'd rather not pass the ID every time, `cp config.example.py config.py` and put
it in there. `config.py` is gitignored.

## 2. Look at it locally

```bash
python -m http.server 8000 -d site
```

Open http://localhost:8000

## 3. Put it online

Drag the `site/` folder onto https://app.netlify.com/drop and you're live. That's the
whole deploy.

For automatic weekly refreshes, push this repo to GitHub and connect it to Netlify
instead. `.github/workflows/refresh.yml` reruns the fetch every Tuesday at 8am ET,
commits the new JSON, and Netlify redeploys on the commit. Add your league ID as a
repo secret named `LEAGUE_ID` (Settings > Secrets and variables > Actions).

---

## What's on the site

**This Week** — every matchup with projected points, a win probability bar, and the
all-time head-to-head record between those two managers. Plus current standings and
Elo power ratings.

**All-Time** — the franchise ledger (titles, record, win %, points, average finish,
current rating) and the head-to-head matrix: every manager against every other
manager, across the entire history of the league. Green means you own the matchup.

**Seasons** — the title ribbon across the top, one tile per year. Click any year for
that season's final standings and every weekly score.

**Trophy Case** — every piece of hardware in league history. Two trophies a year: the
championship, and the scoring crown for the most regular season points. Gold diamonds for
titles, silver triangles for crowns, and an empty shelf if you've won nothing. The
year-by-year table shows who took what, by how much, and where the champion actually
finished in scoring, which is often embarrassingly low. Winning both in one year is the
**double**, and it's rare.

Scoring crowns use regular season points only. Playoff teams play extra games, so
including the postseason would not be a fair comparison.

**Managers** — click any name for their career file: all-time record, titles, luck,
rating peak, best and worst weeks ever, longest streaks, belt defenses, and their
record against every other manager.

**Record Book** — highest week, lowest week, biggest blowout, closest game, most titles,
longest drought, luckiest career, most robbed by the schedule, and the all-time top 25
single weeks (plus the 25 most embarrassing).

---

## Luck, and why it will start fights

Every week, the script compares each team's score against **every other team in the
league that week**, not just their opponent. That gives an "all-play" record, which is
what your record would be if the schedule were perfectly fair.

Expected wins is that all-play rate, scaled to games actually played. **Luck is actual
wins minus expected wins.**

A manager at +12 has won twelve more games than their scoring deserved. Someone at -10
has been getting mugged by the schedule for two decades and can finally prove it. The
column is on the All-Time ledger and on every manager's profile, both career-long and
broken out season by season.

---

## How the projections work

Two signals, blended:

1. **ESPN's projection.** ESPN projects points for each starter. The script sums the
   starting lineups and converts the projected margin into a win probability using a
   normal distribution, scaled by the actual standard deviation of margins in *your*
   league's history. So a 12 point projected edge means something different in a
   high-variance league than a low-variance one.

2. **Elo.** Every game in league history updates a rating. Blowouts move ratings more
   than one-point wins, but with a dampened multiplier so a 90 point beatdown doesn't
   count triple. Ratings regress 30% toward the mean between seasons, because rosters
   turn over.

The final number is 60% ESPN, 40% Elo. All of that is tunable at the top of
`fetch_data.py`:

```python
ELO_START     = 1500.0
ELO_K         = 24.0    # how much one game moves a rating
ELO_REGRESSION = 0.30   # pulled back toward 1500 between seasons
BLEND_ESPN    = 0.60    # ESPN projection vs. Elo
```

Turn `BLEND_ESPN` down if you think ESPN's projections are garbage. Turn `ELO_K` up
if you want ratings to react faster.

---

## Two things worth knowing

**Franchises are tracked by human, not team name and not ESPN account.** ESPN gives each
league member a GUID that survives team renames. What it does not survive is someone
leaving the league and rejoining on a *new ESPN account*, which over twenty years happens
constantly. So identity resolves in three layers:

1. Same GUID, obviously the same person
2. Same name, auto-merged (this catches nicknames too: Nick/Nicholas, Dan/Daniel, Bill/William)
3. `aliases.json`, for anything a machine shouldn't guess at

The script prints any pairs it thought *might* be the same person but didn't merge, and
the Managers tab shows them too. If a pair is one human, add it to `aliases.json`:

```json
{
  "merge": [
    ["Bobby Digital", "Robert DiGiacomo"]
  ],
  "rename": {
    "R D": "Rob Delaney"
  }
}
```

Then rerun the fetch. The first name in each merge group is the one displayed, unless
you override it under `rename`.

**Older seasons will be thinner.** ESPN rewrote its fantasy API around 2018. Seasons
before that come through a legacy endpoint that often returns standings but no weekly
box scores, and the very earliest years may return nothing at all. The script handles
this without crashing and tells you exactly which years came back incomplete.

If a year you care about is missing, you can hand-edit `site/data/league.json` and
add the season by following the shape of the ones that worked. For a twenty year
league, backfilling a few early seasons by hand is usually worth the hour.

---

## Files

```
fetch_data.py           pulls ESPN, computes everything, writes the JSON
make_sample_data.py     generates the fake league currently loaded
config.example.py       copy to config.py, add your league ID
site/
  index.html
  styles.css
  app.js
  data/league.json      the only thing that changes week to week
netlify.toml            tells Netlify to publish site/ with no build step
.github/workflows/      weekly auto-refresh
```
