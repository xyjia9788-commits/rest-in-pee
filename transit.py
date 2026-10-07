"""NYC transit model for The Best Day for AI GTM.
Stations: MTA Subway Stations (NY Open Data, data.ny.gov 39hk-dx4f) + PATH (Port Authority).
Transfers = fewest line changes between two stations, using a line graph where two lines touch
if one station (or two stations <250 m apart, i.e. an in-system/street transfer) serves both."""
import json, math, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))

PATH_STATIONS = [  # name, lat, lon, PATH lines
    ("Journal Square (PATH)", 40.73301, -74.06289, ["PATH-JSQ-33", "PATH-NWK-WTC"]),
    ("Grove Street (PATH)", 40.71966, -74.04288, ["PATH-JSQ-33", "PATH-NWK-WTC"]),
    ("Exchange Place (PATH)", 40.71676, -74.03277, ["PATH-NWK-WTC", "PATH-HOB-WTC"]),
    ("Newport (PATH)", 40.72699, -74.03383, ["PATH-JSQ-33", "PATH-HOB-WTC"]),
    ("Hoboken (PATH)", 40.73586, -74.02894, ["PATH-HOB-33", "PATH-HOB-WTC"]),
    ("World Trade Center (PATH)", 40.71271, -74.01193, ["PATH-NWK-WTC", "PATH-HOB-WTC"]),
    ("Christopher Street (PATH)", 40.73291, -74.00707, ["PATH-JSQ-33", "PATH-HOB-33"]),
    ("9th Street (PATH)", 40.73424, -73.99880, ["PATH-JSQ-33", "PATH-HOB-33"]),
    ("14th Street (PATH)", 40.73732, -73.99684, ["PATH-JSQ-33", "PATH-HOB-33"]),
    ("23rd Street (PATH)", 40.74291, -73.99266, ["PATH-JSQ-33", "PATH-HOB-33"]),
    ("33rd Street (PATH)", 40.74914, -73.98808, ["PATH-JSQ-33", "PATH-HOB-33"]),
]


def km(a_lat, a_lon, b_lat, b_lon):
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def load_stations():
    raw = json.load(open(os.path.join(HERE, "mta_stations.json")))
    out = []
    for s in raw:
        routes = [r for r in (s.get("daytime_routes") or "").split() if r]
        if not routes:
            continue
        out.append({"name": f"{s['stop_name']} ({'/'.join(routes)})", "system": "subway",
                    "lat": float(s["gtfs_latitude"]), "lon": float(s["gtfs_longitude"]), "routes": routes})
    for n, la, lo, rr in PATH_STATIONS:
        out.append({"name": n, "system": "PATH", "lat": la, "lon": lo, "routes": rr})
    return out


STATIONS = load_stations()


def _line_graph():
    g = collections.defaultdict(set)
    for s in STATIONS:
        for a in s["routes"]:
            for b in s["routes"]:
                if a != b:
                    g[a].add(b)
    # street/in-system transfers between nearby stations (e.g. 33rd St PATH <-> 34 St-Herald Sq)
    for i, s in enumerate(STATIONS):
        for t in STATIONS[i + 1:]:
            if km(s["lat"], s["lon"], t["lat"], t["lon"]) < 0.25:
                for a in s["routes"]:
                    for b in t["routes"]:
                        if a != b:
                            g[a].add(b); g[b].add(a)
    return g


LINES = _line_graph()


def line_hops(a_routes, b_routes):
    """fewest line changes between any route at A and any route at B (0 = one-seat ride)."""
    best = 9
    for a in a_routes:
        if a in b_routes:
            return 0
        seen, q = {a: 0}, collections.deque([a])
        while q:
            x = q.popleft()
            if x in b_routes:
                best = min(best, seen[x]); break
            for y in LINES[x]:
                if y not in seen:
                    seen[y] = seen[x] + 1; q.append(y)
    return best


def nearest(lat, lon, k=3, max_km=0.9):
    c = sorted(((km(lat, lon, s["lat"], s["lon"]), s) for s in STATIONS), key=lambda x: x[0])
    return [dict(s, walk_km=round(d, 2)) for d, s in c[:k] if d <= max_km] or [dict(c[0][1], walk_km=round(c[0][0], 2))]


def trip(a, b):
    """a, b: dicts with lat/lon. -> {mode, minutes, transfers, from, to, lines, walk_km}"""
    d = km(a["lat"], a["lon"], b["lat"], b["lon"])
    if d <= 1.1:
        return {"mode": "walk", "minutes": round(d * 1000 / 80), "transfers": 0, "walk_km": round(d, 2),
                "from": "", "to": "", "lines": []}
    best = None
    for sa in nearest(a["lat"], a["lon"]):
        for sb in nearest(b["lat"], b["lon"]):
            hops = line_hops(sa["routes"], sb["routes"])
            if hops > 3:
                continue
            ride = km(sa["lat"], sa["lon"], sb["lat"], sb["lon"]) * 2.4 + 4      # ~25 km/h incl. stops + wait
            mins = (sa["walk_km"] + sb["walk_km"]) * 1000 / 80 + ride + hops * 7
            cand = {"mode": "transit", "minutes": round(mins), "transfers": hops, "walk_km": round(sa["walk_km"] + sb["walk_km"], 2),
                    "from": sa["name"], "to": sb["name"],
                    "lines": sorted(set(sa["routes"]) & set(sb["routes"])) or [sa["routes"][0] + "→" + sb["routes"][0]]}
            if best is None or (cand["transfers"], cand["minutes"]) < (best["transfers"], best["minutes"]):
                best = cand
    return best or {"mode": "taxi", "minutes": round(d * 3 + 8), "transfers": 0, "walk_km": 0, "from": "", "to": "", "lines": []}


if __name__ == "__main__":
    home = {"lat": 40.73301, "lon": -74.06289}           # Journal Square
    herald = {"lat": 40.7497, "lon": -73.9877}
    soho = {"lat": 40.7233, "lon": -73.9990}
    print(len(STATIONS), "stations")
    print("JSQ -> Herald Sq:", trip(home, herald))
    print("JSQ -> SoHo:", trip(home, soho))
    print("Herald -> SoHo:", trip(herald, soho))
