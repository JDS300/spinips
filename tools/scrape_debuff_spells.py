"""Scrape Allakhazam for debuff spell durations and landing prose.

Output: spells.json  { name: {id, duration_raw, endpoints, cast_on_other, classes} }
Run once; the result is committed as reference data, not re-scraped at build time.
"""
import json, re, subprocess, sys, time, pathlib, html

HERE = pathlib.Path(__file__).parent
UA = "Mozilla/5.0 (compatible; spinips-debuff-table/1.0)"

CLASS_LISTS = {
    "shm": "https://everquest.allakhazam.com/db/spelllist.html?name=&type=shm&level=1&opt=And+Higher&action=search",
    "nec": "https://everquest.allakhazam.com/db/spelllist.html?name=&type=nec&level=1&opt=And+Higher&action=search",
    "dru": "https://everquest.allakhazam.com/db/spelllist.html?name=&type=dru&level=1&opt=And+Higher&action=search",
    "enc": "https://everquest.allakhazam.com/db/spelllist.html?name=&type=enc&level=1&opt=And+Higher&action=search",
    "bst": "https://everquest.allakhazam.com/db/spelllist.html?name=&type=bst&level=1&opt=And+Higher&action=search",
}

WANTED = {
    # slow
    "Drowsy": "slow", "Walking Sleep": "slow", "Tagar's Insects": "slow",
    "Togor's Insects": "slow", "Languid Pace": "slow", "Tepid Deeds": "slow",
    "Shiftless Deeds": "slow", "Sha's Lethargy": "slow",
    # resist
    "Malaise": "resist", "Malaisement": "resist", "Malosi": "resist",
    "Tashina": "resist", "Tashani": "resist", "Tashania": "resist",
    # dot
    "Sicken": "dot", "Tainted Breath": "dot", "Infectious Cloud": "dot",
    "Insidious Fever": "dot", "Affliction": "dot", "Scourge": "dot",
    "Insidious Malady": "dot", "Plague": "dot", "Envenomed Bolt": "dot",
    "Disease Cloud": "dot", "Poison Bolt": "dot", "Clinging Darkness": "dot",
    "Engulfing Darkness": "dot", "Heat Blood": "dot", "Heart Flutter": "dot",
    "Shock of Poison": "dot", "Dooming Darkness": "dot", "Boil Blood": "dot",
    "Venom of the Snake": "dot", "Cascading Darkness": "dot", "Ignite Blood": "dot",
    "Flame Lick": "dot", "Stinging Swarm": "dot", "Creeping Crud": "dot",
    "Immolate": "dot", "Drones of Doom": "dot", "Drifting Death": "dot",
    "Shallow Breath": "dot", "Suffocating Sphere": "dot", "Choke": "dot",
    "Suffocate": "dot", "Gasping Embrace": "dot", "Envenomed Breath": "dot",
}


def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 2000:
        return dest.read_text(errors="replace")
    subprocess.run(["curl", "-sL", "-A", UA, "--max-time", "45", "-o", str(dest), url],
                   check=True)
    time.sleep(1.0)
    return dest.read_text(errors="replace")


LINK_RE = re.compile(r'spell\.html\?spell=(\d+)"[^>]*>([^<]+)')
DUR_RE = re.compile(r"([\d.]+ (?:mins?|ticks?|secs?) @L\d+(?: to [\d.]+ (?:mins?|ticks?|secs?) @L\d+)?)")
OTHER_RE = re.compile(r"Soandso\s+([^<\"]{2,70}?)\.(?:<|\")")


def parse_endpoints(raw):
    """'1.4 mins @L27 to 3.5 mins @L70' -> [(27, 14), (70, 35)] in ticks."""
    out = []
    for value, unit, level in re.findall(r"([\d.]+) (mins?|ticks?|secs?) @L(\d+)", raw):
        v = float(value)
        if unit.startswith("min"):
            ticks = round(v * 60 / 6)
        elif unit.startswith("sec"):
            ticks = round(v / 6)
        else:
            ticks = round(v)
        out.append((int(level), ticks))
    return out


def main():
    cache = HERE / "cache"
    cache.mkdir(exist_ok=True)

    index = {}   # spell name -> id
    classes = {} # spell name -> {class: level}
    for cls, url in CLASS_LISTS.items():
        page = fetch(url, cache / f"list_{cls}.html")
        found = 0
        for sid, name in LINK_RE.findall(page):
            name = html.unescape(name).strip()
            index.setdefault(name, sid)
            found += 1
        print(f"  {cls}: {found} spell links", file=sys.stderr)

    results, missing = {}, []
    for name, kind in sorted(WANTED.items()):
        sid = index.get(name)
        if not sid:
            missing.append(name)
            continue
        page = fetch(f"https://everquest.allakhazam.com/db/spell.html?spell={sid}",
                     cache / f"spell_{sid}.html")
        dur = DUR_RE.search(page)
        other = OTHER_RE.search(page)
        raw = dur.group(1) if dur else None
        results[name] = {
            "id": sid,
            "kind": kind,
            "duration_raw": raw,
            "endpoints": parse_endpoints(raw) if raw else [],
            "cast_on_other": re.sub(r"\s+", " ", other.group(1)).strip() if other else None,
        }
        print(f"  {name:24s} id={sid:5s} {raw or 'NO DURATION':38s} "
              f"{results[name]['cast_on_other'] or '-'}", file=sys.stderr)

    (HERE / "spells.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nscraped={len(results)} missing={missing}", file=sys.stderr)


main()
