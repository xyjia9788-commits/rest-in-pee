#!/usr/bin/env python3
"""Restroom Rescue — ON THE TRAIN mode.

"I got on at 50 St at 7 pm and I'll need a bathroom in ~10 minutes. Where do I get off?"
For every stop ahead on your line (real MTA GTFS schedule), total = ride + 2 min to street + walk to a restroom
that is OPEN at the minute you arrive (Elastic geo + hours filters). Pick the smallest total within the budget.

  python3 onboard.py "I got on the 1 at 50 St going downtown at 7 pm, I have 10 minutes"
  python3 onboard.py coverage            # verify every Manhattan station, both directions, 19:00 / 22:00 / 01:00
"""
import csv, collections, json, math, os, sys
import bestday as B
import rescue as R

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.join(HERE, "gtfs")
EXIT_MIN = 2          # platform -> street
WALK_M_PER_MIN = 80


def hm(s):
    h, m, sec = (int(x) for x in s.split(":"))
    return h * 60 + m + sec / 60


# ── schedule ───────────────────────────────────────────────────────────────
STOPS = {r["stop_id"]: r for r in csv.DictReader(open(os.path.join(G, "stops.txt")))}
PARENT = {sid: (r["parent_station"] or sid) for sid, r in STOPS.items()}
TRIPS = {r["trip_id"]: r for r in csv.DictReader(open(os.path.join(G, "trips.txt")))}
_seq = collections.defaultdict(list)
for r in csv.DictReader(open(os.path.join(G, "stop_times.txt"))):
    t = TRIPS.get(r["trip_id"])
    if t and "Weekday" in t["service_id"]:
        _seq[r["trip_id"]].append((int(r["stop_sequence"]), PARENT[r["stop_id"]], hm(r["arrival_time"])))
BY_RD = collections.defaultdict(list)       # (route, dir) -> [(start_min, [(parent, t), ...])]
for tid, rows in _seq.items():
    rows.sort()
    t = TRIPS[tid]
    BY_RD[(t["route_id"], t["direction_id"])].append((rows[0][2], [(p, tt) for _, p, tt in rows]))
HEAD = {}
for t in TRIPS.values():
    HEAD.setdefault((t["route_id"], t["direction_id"]), t["trip_headsign"])

MTA = json.load(open(os.path.join(HERE, "mta_stations.json")))
STATION = {s["gtfs_stop_id"]: s for s in MTA}


def st_name(pid):
    s = STATION.get(pid)
    return f"{s['stop_name']} ({s['daytime_routes'].replace(' ', '/')})" if s else STOPS.get(pid, {}).get("stop_name", pid)


def st_ll(pid):
    s = STOPS[pid]
    return float(s["stop_lat"]), float(s["stop_lon"])


def trip_through(route, d, pid, t):
    """the scheduled trip of this route/direction that reaches station pid closest to (and not before) minute t."""
    best = None
    for start, seq in BY_RD.get((route, d), []):
        for i, (p, tt) in enumerate(seq):
            if p == pid:
                for off in (0, 1440):
                    if tt + off >= t - 1:
                        gap = tt + off - t
                        if best is None or gap < best[0]:
                            best = (gap, seq, i, off)
                break
    return best


# ── restrooms (Elastic) ────────────────────────────────────────────────────
_cache = {}


def nearest_open(e, lat, lon, minute, max_m, day="thu"):
    """nearest restroom open at `minute` within max_m: public first; if none, 24/7 places. -> (src, meters, kind) | None"""
    minute = int(minute) % 1440
    key = (round(lat, 5), round(lon, 5), minute // 5, max_m // 50)
    if key in _cache:
        return _cache[key]
    hits, _ = R.find(e, lat, lon, day, minute, max_m=max_m, size=1)
    res = (hits[0][0], hits[0][1], "public") if hits else None
    if not res:
        late = R.late_options(e, lat, lon, max_m=max_m)
        if late:
            s, m = sorted(late, key=lambda x: (x[0]["tier"], x[1]))[0]
            res = (s, m, "24/7 place")
    _cache[key] = res
    return res


def best_exit(e, routes, pid, t, budget=10, dirs=("0", "1"), on_train=True):
    """over every route/direction you might be on: best station to get off at. -> list of options sorted by total"""
    opts = []
    for r in routes:
        for d in dirs:
            tr = trip_through(r, d, pid, t)
            if not tr:
                continue
            gap, seq, i, off = tr
            t0 = seq[i][1] + off
            for p, tt in seq[i + (1 if on_train else 0):]:
                ride = tt + off - t0
                if ride + EXIT_MIN >= budget:
                    break
                lat, lon = st_ll(p)
                left_m = int((budget - ride - EXIT_MIN) * WALK_M_PER_MIN)
                hit = nearest_open(e, lat, lon, t + ride + EXIT_MIN, left_m)
                if hit:
                    s, m, kind = hit
                    walk = m / WALK_M_PER_MIN
                    opts.append({"route": r, "dir": d, "toward": HEAD.get((r, d), ""), "get_off": p, "get_off_name": st_name(p),
                                 "stops": seq.index((p, tt)) - i, "ride": round(ride), "walk": math.ceil(walk),
                                 "total": math.ceil(ride + EXIT_MIN + walk), "restroom": s.get("name"), "kind": kind,
                                 "note": s.get("note") or (s.get("type") or ""), "rlat": s["location"]["lat"], "rlon": s["location"]["lon"],
                                 "slat": lat, "slon": lon})
    opts.sort(key=lambda o: (o["kind"] != "public", o["total"]))
    return opts


PROMPT = """From the rider's message extract JSON: {"station": name as written, "routes": list of subway line letters/numbers they are on
(empty if unknown), "direction": "uptown" | "downtown" | "unknown", "time": "HH:MM" 24h, "minutes_left": integer (default 10)}"""


def onboard(msg):
    c, e = B.mistral(), B.es()
    p = B.jload(c.chat.complete(model=B.SMALL, response_format={"type": "json_object"}, temperature=0,
                                messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": msg}]).choices[0].message.content)
    st = B.station_by_name(p.get("station"), p.get("routes"))
    # all GTFS parents with that station name (50 St has one for the 1 and one for the C/E)
    base = st["name"].split(" (")[0]
    want = [r.upper() for r in (p.get("routes") or [])]
    pids = [s["gtfs_stop_id"] for s in MTA if s["stop_name"] == base
            and (set(want) & set(s["daytime_routes"].split()) if want else
                 B.T.km(st["lat"], st["lon"], float(s["gtfs_latitude"]), float(s["gtfs_longitude"])) < 0.4)]
    t = R.mins(p.get("time") or "19:00")
    budget = int(p.get("minutes_left") or 10)
    dirs = {"uptown": ("0",), "downtown": ("1",)}.get(p.get("direction"), ("0", "1"))
    print(f"① Mistral: you're on {want or 'any line'} at {base}, {p.get('direction')}, {p.get('time')}, {budget} min left")
    opts = []
    for pid in pids:
        routes = want or STATION[pid]["daytime_routes"].split()
        routes = [r for r in routes if r in STATION[pid]["daytime_routes"].split()] or STATION[pid]["daytime_routes"].split()
        opts += best_exit(e, routes, pid, t, budget, dirs)
    if not opts:
        print(f"② No restroom reachable within {budget} min from here at {p.get('time')}.")
        return
    seen, uniq = set(), []
    for x in opts:
        k = (x["get_off"], x["restroom"])
        if k not in seen:
            seen.add(k); uniq.append(x)
    opts = uniq
    o = opts[0]
    print(f"② Checked every stop ahead (MTA schedule) × restrooms open at your arrival minute (Elastic)…")
    print(f"③ {'Stay on for ' + str(o['stops']) + ' stop(s) and get' if o['stops'] else 'Get'} off at {o['get_off_name']} "
          f"({o['route']} toward {o['toward']}), {o['ride']} min ride + {EXIT_MIN} min to street + {o['walk']} min walk")
    print(f"   🚻 {o['restroom']} — {o['kind']}{' · ' + o['note'] if o['note'] else ''} · total ≈ {o['total']} min (budget {budget})")
    for x in opts[1:3]:
        print(f"   alt: {x['get_off_name']} → {x['restroom']} ({x['kind']}) ≈ {x['total']} min")
    json.dump({"msg": msg, "parsed": p, "best": o, "alts": opts[1:4]}, open(os.path.join(HERE, "onboard_out.json"), "w"), ensure_ascii=False)


def coverage(times=("19:00", "22:00", "01:00"), budget=10):
    e = B.es()
    man = [s for s in MTA if s["borough"] == "M"]
    out = {}
    for tt in times:
        t = R.mins(tt)
        rows = []
        for s in man:
            pid = s["gtfs_stop_id"]
            res = {}
            for d in ("0", "1"):
                o = best_exit(e, s["daytime_routes"].split(), pid, t, budget, (d,))
                pub = [x for x in o if x["kind"] == "public"]
                res[d] = {"public": pub[0]["total"] if pub else None, "any": o[0]["total"] if o else None,
                          "best": (pub or o or [None])[0]}
            rows.append({"pid": pid, "name": st_name(pid), "lat": float(s["gtfs_latitude"]), "lon": float(s["gtfs_longitude"]), "dirs": res})
        n = len(rows) * 2
        pub_ok = sum(1 for r in rows for d in r["dirs"].values() if d["public"] is not None)
        any_ok = sum(1 for r in rows for d in r["dirs"].values() if d["any"] is not None)
        print(f"{tt}: Manhattan station-directions with a FREE public restroom ≤{budget} min: {pub_ok}/{n} ({100 * pub_ok // n}%) · "
              f"incl. 24/7 places: {any_ok}/{n} ({100 * any_ok // n}%)")
        out[tt] = rows
    json.dump(out, open(os.path.join(HERE, "coverage.json"), "w"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    if sys.argv[1:] == ["coverage"]:
        coverage()
    else:
        onboard(" ".join(sys.argv[1:]))
