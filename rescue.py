#!/usr/bin/env python3
"""Restroom Rescue — just got off the subway in NYC: the nearest FREE public restroom that is OPEN RIGHT NOW,
within a 10-minute walk.

  python3 rescue.py index                                   # Elastic: 1,066 NYC Open Data restrooms + Mistral-normalized hours
  python3 rescue.py "Just got off at 14 St-Union Sq, it's 11:40 pm on a Thursday"

Mistral reads the sentence (station, day, time, needs), Elastic runs geo_distance + "open at this minute" filters."""
import json, os, re, sys, datetime as dt
import bestday as B

IDX = "nyc_public_restrooms"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
HERE = os.path.dirname(os.path.abspath(__file__))


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


LATE = "nyc_late_night"
TIER = {"ferry_terminal": (1, "free · public terminal, open 24/7"),
        "fast_food": (2, "open 24/7 · customers only — buy something small (restroom code often on the receipt)"),
        "restaurant": (2, "open 24/7 diner · customers only"), "cafe": (2, "open 24/7 · customers only"),
        "hotel": (3, "hotel lobby, open 24/7 · ask the front desk")}


def index_late():
    e = B.es()
    els = json.load(open(os.path.join(HERE, "osm_24h.json")))["elements"]
    if e.indices.exists(index=LATE):
        e.indices.delete(index=LATE)
    e.indices.create(index=LATE, mappings={"properties": {"name": {"type": "text", "fields": {"k": {"type": "keyword"}}},
        "kind": {"type": "keyword"}, "tier": {"type": "integer"}, "note": {"type": "text"}, "toilets": {"type": "keyword"},
        "location": {"type": "geo_point"}}})
    from elasticsearch.helpers import bulk
    docs = []
    for x in els:
        t = x.get("tags", {})
        if t.get("opening_hours") != "24/7":
            continue
        kind = t.get("amenity") or t.get("tourism") or t.get("shop")
        if kind not in TIER or not t.get("name"):
            continue
        if re.search(r"dunkin|krispy kreme", t["name"], re.I):      # verified 10/7: no customer restroom / not 24/7
            continue
        lat = x.get("lat") or (x.get("center") or {}).get("lat"); lon = x.get("lon") or (x.get("center") or {}).get("lon")
        tier, note = TIER[kind]
        docs.append({"_index": LATE, "_source": {"name": t["name"], "kind": kind, "tier": tier, "note": note,
                                                 "toilets": t.get("toilets", ""), "location": {"lat": lat, "lon": lon}}})
    ok, _ = bulk(e, docs)
    e.indices.refresh(index=LATE)
    print(f"indexed {ok} 24/7 places (OpenStreetMap opening_hours=24/7) into {LATE}")


def late_options(e, lat, lon, max_m=800):
    r = e.search(index=LATE, size=6, query={"bool": {"filter": [{"geo_distance": {"distance": f"{max_m}m", "location": {"lat": lat, "lon": lon}}}]}},
                 sort=[{"tier": "asc"}, {"_geo_distance": {"location": {"lat": lat, "lon": lon}, "order": "asc", "unit": "m"}}])
    return [(h["_source"], round(h["sort"][1])) for h in r["hits"]["hits"]]


def index():
    e = B.es()
    raw = json.load(open(os.path.join(HERE, "restrooms.json")))
    hours = json.load(open(os.path.join(HERE, "restroom_hours.json")))
    props = {"name": {"type": "text"}, "type": {"type": "keyword"}, "operator": {"type": "keyword"},
             "status": {"type": "keyword"}, "hours_text": {"type": "text"}, "changing_stations": {"type": "keyword"},
             "accessible": {"type": "keyword"}, "restroom_type": {"type": "keyword"}, "location": {"type": "geo_point"}}
    for d in DAYS:
        props[f"{d}_open"] = {"type": "integer"}; props[f"{d}_close"] = {"type": "integer"}
    if e.indices.exists(index=IDX):
        e.indices.delete(index=IDX)
    e.indices.create(index=IDX, mappings={"properties": props})
    from elasticsearch.helpers import bulk
    docs = []
    for x in raw:
        if not x.get("latitude"):
            continue
        h = hours.get((x.get("hours_of_operation") or "").strip()) or {}
        src = {"name": x.get("facility_name"), "type": x.get("location_type"), "operator": x.get("operator"),
               "status": x.get("status"), "hours_text": x.get("hours_of_operation") or "", "accessible": x.get("accessibility"),
               "changing_stations": x.get("changing_stations"), "restroom_type": x.get("restroom_type"),
               "location": {"lat": float(x["latitude"]), "lon": float(x["longitude"])}}
        for d in DAYS:
            v = h.get(d) if isinstance(h, dict) else None
            if v and len(v) == 2 and v[0] and v[1]:
                src[f"{d}_open"], src[f"{d}_close"] = mins(v[0]), mins(v[1])
        docs.append({"_index": IDX, "_source": src})
    ok, _ = bulk(e, docs)
    e.indices.refresh(index=IDX)
    print(f"indexed {ok} restrooms with Mistral-normalized opening hours into {IDX}")


PROMPT = """Extract from the message: {"station": subway/PATH station name as written, "routes": list of line letters/numbers if given,
"day": one of mon,tue,wed,thu,fri,sat,sun (default thu), "time": "HH:MM" 24h (default now), "needs_changing_table": bool,
"needs_accessible": bool}. JSON only."""


def find(e, lat, lon, day, t, max_m=800, size=3, extra=()):
    q = {"bool": {"filter": [{"term": {"status": "Operational"}},
                             {"geo_distance": {"distance": f"{max_m}m", "location": {"lat": lat, "lon": lon}}},
                             {"range": {f"{day}_open": {"lte": t}}}, {"range": {f"{day}_close": {"gt": t}}}, *extra]}}
    r = e.search(index=IDX, size=size, query=q,
                 sort=[{"_geo_distance": {"location": {"lat": lat, "lon": lon}, "order": "asc", "unit": "m"}}])
    return [(h["_source"], round(h["sort"][0])) for h in r["hits"]["hits"]], q


def count_open(e, lat, lon, day, t, max_m=800):
    return e.count(index=IDX, query={"bool": {"filter": [
        {"term": {"status": "Operational"}}, {"geo_distance": {"distance": f"{max_m}m", "location": {"lat": lat, "lon": lon}}},
        {"range": {f"{day}_open": {"lte": t}}}, {"range": {f"{day}_close": {"gt": t}}}]}})["count"]


def rescue(msg):
    c, e = B.mistral(), B.es()
    p = B.jload(c.chat.complete(model=B.SMALL, response_format={"type": "json_object"}, temperature=0,
                                messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": msg}]).choices[0].message.content)
    st = B.station_by_name(p.get("station"), p.get("routes"))
    day, hhmm = p.get("day") or "thu", p.get("time") or dt.datetime.now().strftime("%H:%M")
    t = mins(hhmm)
    print(f"① Mistral understood: station={st['name']}  day={day}  time={hhmm}  changing_table={p.get('needs_changing_table')}")
    extra = []
    if p.get("needs_changing_table"):
        extra.append({"term": {"changing_stations": "Yes"}})
    hits, q = find(e, st["lat"], st["lon"], day, t, extra=extra)
    print(f"② Elastic: open at {hhmm} on {day}, operational, ≤ 800 m (10-min walk) from {st['name']}")
    print("   " + json.dumps({"filter": [f["range"] if "range" in f else list(f)[0] for f in q["bool"]["filter"]]})[:180])
    afternoon = count_open(e, st["lat"], st["lon"], day, 15 * 60)
    now_n = count_open(e, st["lat"], st["lon"], day, t)
    print(f"   open within 10 min walk: {afternoon} at 15:00 → {now_n} at {hhmm}")
    out = []
    if hits:
        print("③ Go here:")
        for s, m in hits:
            close = s.get(f"{day}_close")
            print(f"   🚻 {s['name']} ({s['type']}) · {m} m · ~{max(1, round(m / 80))} min walk · open until {close // 60:02d}:{close % 60:02d}"
                  + (" · changing table" if s.get("changing_stations") == "Yes" else ""))
            out.append({**s, "m": m})
    else:
        late = late_options(e, st["lat"], st["lon"])
        if late:
            print(f"③ No public restroom is open at {hhmm}. Places open 24/7 within a 10-min walk (Elastic, sorted: free first, then distance):")
            for s, m in late[:4]:
                print(f"   🚻 {s['name']} · {m} m · ~{max(1, round(m / 80))} min walk · {s['note']}")
                out.append({**s, "m": m})
        far, _ = find(e, st["lat"], st["lon"], day, t, max_m=4000, size=1, extra=extra)
        if far and not late:
            s, m = far[0]
            near_st = B.T.nearest(s["location"]["lat"], s["location"]["lon"], k=1)[0]
            tr = B.T.trip(st, {"lat": s["location"]["lat"], "lon": s["location"]["lon"]})
            print(f"③ Nothing open within 10 minutes. Closest open one: 🚻 {s['name']} — {m} m away. "
                  f"Ride {tr['from']} → {tr['to']} ({tr['minutes']} min, {tr['transfers']} transfer(s)), it's {round(near_st['walk_km'] * 1000)} m from {near_st['name']}.")
            out.append({**s, "m": m})
        elif not late:
            print("③ Nothing open nearby at this hour. (Honest answer: NYC has very few public restrooms open late.)")
    json.dump({"station": st, "day": day, "time": hhmm, "hits": out, "afternoon": afternoon, "now": now_n},
              open(os.path.join(HERE, "rescue_out.json"), "w"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    if sys.argv[1:] == ["index"]:
        index(); index_late()
    else:
        rescue(" ".join(sys.argv[1:]))
