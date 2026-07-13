"""
Who is who.

ESPN gives every league member a GUID. That GUID survives team renames, which is
why we key on it rather than team name. What it does NOT survive is a person
leaving the league and coming back on a new ESPN account: new account, new GUID,
and they show up as a stranger.

Over twenty years that happens a lot. So identity resolves in three layers:

  1. Same GUID            -> obviously the same person
  2. Same name            -> same person on a different account (auto-merged)
  3. aliases.json         -> everything a machine shouldn't guess at

Layer 3 is yours to edit. The script prints suspected duplicates it did not
merge on its own, so you can confirm or ignore them.
"""

import difflib
import json
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ALIAS_PATH = os.path.join(HERE, "aliases.json")

# Common short forms. Extend freely.
NICKNAMES = {
    "nick": "nicholas", "nicky": "nicholas",
    "mike": "michael", "mikey": "michael",
    "dave": "david", "davey": "david",
    "chris": "christopher", "topher": "christopher",
    "tony": "anthony", "ant": "anthony",
    "steve": "steven", "stevie": "steven",
    "matt": "matthew", "matty": "matthew",
    "jim": "james", "jimmy": "james", "jamie": "james",
    "bob": "robert", "bobby": "robert", "rob": "robert", "robbie": "robert",
    "bill": "william", "billy": "william", "will": "william",
    "dan": "daniel", "danny": "daniel",
    "joe": "joseph", "joey": "joseph",
    "ben": "benjamin", "benny": "benjamin",
    "tom": "thomas", "tommy": "thomas",
    "ken": "kenneth", "kenny": "kenneth",
    "rick": "richard", "rich": "richard", "dick": "richard", "ricky": "richard",
    "greg": "gregory", "jeff": "jeffrey", "geoff": "jeffrey",
    "ed": "edward", "eddie": "edward", "ted": "edward",
    "pat": "patrick", "patty": "patrick",
    "sam": "samuel", "alex": "alexander", "andy": "andrew", "drew": "andrew",
    "charlie": "charles", "chuck": "charles",
    "ron": "ronald", "ronnie": "ronald",
    "don": "donald", "donnie": "donald",
    "phil": "philip", "pete": "peter", "gene": "eugene",
    "vin": "vincent", "vinny": "vincent", "vince": "vincent",
    "sean": "shawn", "jon": "jonathan", "johnny": "john",
    "zach": "zachary", "josh": "joshua", "nate": "nathan",
    "tim": "timothy", "adri": "adrian",
}


def norm(name):
    """Lowercase, strip punctuation, expand nicknames. 'Nick Rayment' -> 'nicholas rayment'."""
    s = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    parts = [p for p in s.split() if p]
    if not parts:
        return ""
    parts = [NICKNAMES.get(p, p) for p in parts]
    return " ".join(parts)


def load_aliases():
    """
    aliases.json:
      {
        "merge":  [["Nick Rayment", "Nicholas Rayment"], ["Bobby D", "Robert Digital"]],
        "rename": {"R D": "Rob Dinero"}
      }
    Every name in a merge group becomes one franchise. The FIRST name in each
    group is the one displayed, unless overridden by "rename".
    """
    if not os.path.exists(ALIAS_PATH):
        return {"merge": [], "rename": {}}
    try:
        with open(ALIAS_PATH) as f:
            data = json.load(f)
        return {"merge": data.get("merge", []), "rename": data.get("rename", {})}
    except Exception as e:
        print(f"  aliases.json could not be read ({e}). Ignoring it.")
        return {"merge": [], "rename": {}}


class Identity:
    """Resolves ESPN owner records into stable, human-level franchise IDs."""

    def __init__(self):
        self.aliases = load_aliases()
        self.guid_names = defaultdict(set)     # guid -> {display names seen}
        self.guid_teams = defaultdict(set)     # guid -> {team names seen}
        self.guid_years = defaultdict(set)
        self.guid_of_team = {}                 # (year, team_id) -> guid
        self._resolved = None

        # explicit merge groups, keyed by normalized name
        self.forced = {}
        for group in self.aliases["merge"]:
            if not group:
                continue
            head = norm(group[0])
            for member in group:
                self.forced[norm(member)] = head

    # ---- pass 1: look at every team in every season --------------------------

    def observe(self, team, year):
        owners = getattr(team, "owners", None) or []
        guid = None
        display = None
        for o in owners:
            if isinstance(o, dict):
                if o.get("id") and not guid:
                    guid = o["id"]
                first = (o.get("firstName") or "").strip()
                last = (o.get("lastName") or "").strip()
                nm = " ".join(p for p in (first, last) if p) or (o.get("displayName") or "").strip()
                if nm and not display:
                    display = nm
            elif isinstance(o, str) and o.strip() and not guid:
                guid = o.strip()

        if not guid:
            guid = f"legacy::{year}::{team.team_id}"

        if display:
            self.guid_names[guid].add(display)
        self.guid_teams[guid].add(team.team_name)
        self.guid_years[guid].add(year)
        self.guid_of_team[(year, team.team_id)] = guid

    # ---- resolve -------------------------------------------------------------

    def _display_for(self, guid):
        names = self.guid_names.get(guid)
        if names:
            # prefer the longest, which is usually the fullest form
            return sorted(names, key=lambda n: (-len(n), n))[0].title()
        teams = self.guid_teams.get(guid)
        return sorted(teams)[0] if teams else guid

    def resolve(self):
        """Returns (guid -> franchise_id, franchise_id -> display name, suspects)."""
        if self._resolved:
            return self._resolved

        key_of_guid = {}
        for guid in self.guid_years:
            display = self._display_for(guid)
            n = norm(display)
            if not n:
                key_of_guid[guid] = f"guid::{guid}"
                continue
            key_of_guid[guid] = self.forced.get(n, n)

        # display name per franchise
        name_of_key = {}
        for guid, key in key_of_guid.items():
            cand = self._display_for(guid)
            cur = name_of_key.get(key)
            if cur is None or len(cand) > len(cur):
                name_of_key[key] = cand
        for raw, new in self.aliases["rename"].items():
            k = self.forced.get(norm(raw), norm(raw))
            if k in name_of_key:
                name_of_key[k] = new

        suspects = self._suspects(key_of_guid, name_of_key)
        self._resolved = (key_of_guid, name_of_key, suspects)
        return self._resolved

    def _suspects(self, key_of_guid, name_of_key):
        """Names close enough that they might be the same person, but weren't merged."""
        keys = sorted(set(key_of_guid.values()))
        out = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if not a or not b:
                    continue
                ratio = difflib.SequenceMatcher(None, a, b).ratio()
                pa, pb = a.split(), b.split()
                shares_surname = bool(pa) and bool(pb) and pa[-1] == pb[-1]
                prefix = a.startswith(b) or b.startswith(a)
                if ratio >= 0.82 or shares_surname or prefix:
                    out.append({
                        "a": name_of_key.get(a, a), "b": name_of_key.get(b, b),
                        "similarity": round(ratio, 2),
                        "reason": "same surname" if shares_surname else
                                  "one name contains the other" if prefix else "spelled almost the same",
                    })
        return out

    def franchise_id(self, year, team_id):
        key_of_guid, _, _ = self.resolve()
        guid = self.guid_of_team.get((year, team_id))
        return key_of_guid.get(guid, f"guid::{guid}")

    def display(self, fid):
        _, name_of_key, _ = self.resolve()
        return name_of_key.get(fid, fid)

    def report(self, log):
        key_of_guid, name_of_key, suspects = self.resolve()

        # who got auto-merged across accounts?
        by_key = defaultdict(list)
        for guid, key in key_of_guid.items():
            by_key[key].append(guid)
        merged = {k: v for k, v in by_key.items() if len(v) > 1}

        if merged:
            log("")
            log("  Merged across multiple ESPN accounts (same name):")
            for k, guids in merged.items():
                yrs = sorted(set().union(*[self.guid_years[g] for g in guids]))
                log(f"    {name_of_key[k]}: {len(guids)} accounts, {yrs[0]}-{yrs[-1]}")

        if suspects:
            log("")
            log("  Possible duplicates I did NOT merge. If any of these are one person,")
            log("  add them to aliases.json and rerun:")
            for s in suspects:
                log(f'    ["{s["a"]}", "{s["b"]}"]   ({s["reason"]})')
