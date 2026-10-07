#!/usr/bin/env python3
"""The Best Day for AI GTM — Elastic x Mistral NYC Hack Night (2026-10-07).

Give it a person; it plans their best networking day in NYC tomorrow (Thu Oct 8):
the right events, the right venues, the right times, and the fewest subway/PATH transfers.

  python3 bestday.py extract        # Mistral structured outputs: 83 Luma event pages -> clean JSON
  python3 bestday.py index          # Elasticsearch: Mistral inference endpoint + semantic_text + geo_point
  python3 bestday.py plan "<who you are>"   # Mistral agent calls Elastic tools -> plan -> itinerary
  python3 bestday.py agg            # Elastic aggregations: the enterprise view

Data: Luma public event pages (NYC, Oct 8), MTA Subway Stations (NY Open Data 39hk-dx4f), PATH stations,
public host bios only (no LinkedIn scraping).
Keys come from ~/.hacknight.env (MISTRAL_API_KEY, ES_URL, ES_API_KEY); never printed."""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

import transit as T

HERE = os.path.dirname(os.path.abspath(__file__))
NY = ZoneInfo("America/New_York")
DAY = dt.date(2026, 10, 8)
EV_IDX, ST_IDX = "bestday_events", "nyc_transit_stations"
SMALL, LARGE = "mistral-small-latest", "mistral-large-4"


def env():
    p = os.path.expanduser("~/.hacknight.env")
    for line in open(p):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


env()


def mistral():
    from mistralai.client import Mistral
    return Mistral(api_key=os.environ["MISTRAL_API_KEY"])


def es():
    from elasticsearch import Elasticsearch
    return Elasticsearch(os.environ["ES_URL"], api_key=os.environ["ES_API_KEY"], request_timeout=120)



def text_of(content):
    """mistral-large-4 may return a list of chunks (thinking + text); keep the text."""
    if isinstance(content, str):
        return content
    out = []
    for ch in content or []:
        t = getattr(ch, "type", None) or (ch.get("type") if isinstance(ch, dict) else None)
        if t == "text":
            out.append(getattr(ch, "text", None) or ch.get("text", ""))
    return "".join(out)


def jload(content):
    t = text_of(content).strip()
    t = re.sub(r"^```(json)?|```$", "", t, flags=re.M).strip()
    return json.loads(t)


def say(*a):
    print(*a, flush=True)


# ── 1. extract ──────────────────────────────────────────────────────────────
EXTRACT_PROMPT = """You read one NYC event page and return JSON only, with these keys:
"summary": one plain sentence (max 25 words) saying what happens and who it is for,
"format": one of ["breakfast/coffee","run/fitness","conference/summit","panel/talk","workshop","hackathon/build","dinner","happy hour/mixer","demo night","coworking","other"],
"topics": up to 5 short lowercase tags (e.g. "ai agents","fintech","gtm","sales","marketing","security","adtech","founders","careers"),
"audience": up to 4 of ["founders","engineers","gtm/sales","marketing","finance","investors","product","operators","job seekers","creatives","general public"],
"ai_level": 0-3 (0 = not about AI, 3 = AI is the core),
"gtm_fit": 0-3 (how useful for someone building a go-to-market / sales / partnerships career in AI),
"big_companies": list of well-known companies (1000+ employees) named as host, sponsor, venue or speaker,
"companies": all company or organization names mentioned as host/sponsor/speaker (max 8),
"people": up to 5 objects {"name","role"} for named hosts/speakers with what they do (from the page only),
"networking": 0-3 (how much real mingling time there is),
"intensity": "light" | "medium" | "deep" (deep = long talks/building)."""


def extract():
    rows = json.load(open(os.path.join(HERE, "events_1008.json")))
    out_p = os.path.join(HERE, "events_enriched.json")
    done = {r["id"]: r for r in json.load(open(out_p))} if os.path.exists(out_p) else {}
    c = mistral()

    def one(r):
        if r["id"] in done:
            return done[r["id"]]
        page = (f"Title: {r['name']}\nWhen: {r['start'][11:16]}-{r['end'][11:16]}\nWhere: {r['area']} | {r['address']}\n"
                f"Calendar: {r['calendar']}\nHosts: " + "; ".join(f"{h['name']} — {h['bio']}" for h in r["hosts"]) +
                f"\n\n{r['desc'][:2500]}")
        for i in range(4):
            try:
                resp = c.chat.complete(model=SMALL, response_format={"type": "json_object"}, temperature=0,
                                       messages=[{"role": "system", "content": EXTRACT_PROMPT},
                                                 {"role": "user", "content": page}])
                return {**r, "ai": json.loads(resp.choices[0].message.content)}
            except Exception as e:
                time.sleep(2 * (i + 1))
                err = str(e)[:120]
        return {**r, "ai": {"summary": r["name"], "error": err}}

    t0 = time.time()
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(one, rows))
    json.dump(res, open(out_p, "w"), ensure_ascii=False, indent=0)
    bad = sum(1 for r in res if "error" in r["ai"])
    say(f"Mistral ({SMALL}) structured {len(res)} event pages in {time.time() - t0:.0f}s; failures {bad}")
    for r in res[:3]:
        say(" ", r["name"][:50], "->", json.dumps(r["ai"])[:220])


# ── 2. index ────────────────────────────────────────────────────────────────
def index():
    e = es()
    key = os.environ["MISTRAL_API_KEY"]
    for kind, iid, model in (("text_embedding", "mistral-embeddings", "mistral-embed"),
                             ("chat_completion", "mistral-chat", LARGE)):
        try:
            e.perform_request("GET", f"/_inference/{kind}/{iid}", headers={"accept": "application/json"})
            say(f"inference endpoint {iid} exists")
        except Exception:
            e.perform_request("PUT", f"/_inference/{kind}/{iid}",
                              headers={"content-type": "application/json", "accept": "application/json"},
                              body={"service": "mistral", "service_settings": {"api_key": key, "model": model}})
            say(f"created inference endpoint {iid} -> Mistral {model}")
    # stations (NY Open Data + PATH)
    if e.indices.exists(index=ST_IDX):
        e.indices.delete(index=ST_IDX)
    e.indices.create(index=ST_IDX, mappings={"properties": {
        "name": {"type": "text"}, "system": {"type": "keyword"}, "routes": {"type": "keyword"},
        "location": {"type": "geo_point"}}})
    from elasticsearch.helpers import bulk
    bulk(e, ({"_index": ST_IDX, "_source": {"name": s["name"], "system": s["system"], "routes": s["routes"],
                                            "location": {"lat": s["lat"], "lon": s["lon"]}}} for s in T.STATIONS))
    e.indices.refresh(index=ST_IDX)
    say(f"indexed {len(T.STATIONS)} stations into {ST_IDX}")
    # events
    rows = json.load(open(os.path.join(HERE, "events_enriched.json")))
    if e.indices.exists(index=EV_IDX):
        e.indices.delete(index=EV_IDX)
    e.indices.create(index=EV_IDX, mappings={"properties": {
        "name": {"type": "text"}, "profile": {"type": "semantic_text", "inference_id": "mistral-embeddings"},
        "summary": {"type": "text"}, "start": {"type": "date"}, "end": {"type": "date"},
        "location": {"type": "geo_point"}, "area": {"type": "keyword"}, "format": {"type": "keyword"},
        "topics": {"type": "keyword"}, "audience": {"type": "keyword"}, "companies": {"type": "keyword"},
        "big_companies": {"type": "keyword"}, "ai_level": {"type": "integer"}, "gtm_fit": {"type": "integer"},
        "networking": {"type": "integer"}, "guests": {"type": "integer"}, "free": {"type": "boolean"},
        "near_stations": {"type": "keyword"}, "near_routes": {"type": "keyword"},
        "people": {"type": "object", "enabled": False}, "url": {"type": "keyword"}}})
    docs = []
    for r in rows:
        a = r.get("ai") or {}
        # nearest stations via an Elastic geo_distance query
        q = e.search(index=ST_IDX, size=3, query={"geo_distance": {"distance": "900m", "location": {"lat": r["lat"], "lon": r["lon"]}}},
                     sort=[{"_geo_distance": {"location": {"lat": r["lat"], "lon": r["lon"]}, "order": "asc", "unit": "m"}}])
        near = [(h["_source"]["name"], h["_source"]["routes"], round(h["sort"][0])) for h in q["hits"]["hits"]]
        docs.append({"_index": EV_IDX, "_id": r["id"], "_source": {
            "name": r["name"], "summary": a.get("summary", ""), "url": r["url"],
            "profile": f"{r['name']}. {a.get('summary', '')} Topics: {', '.join(a.get('topics', []))}. "
                       f"Audience: {', '.join(a.get('audience', []))}. Format: {a.get('format', '')}. {r['desc'][:1200]}",
            "start": r["start"], "end": r["end"], "location": {"lat": r["lat"], "lon": r["lon"]}, "area": r["area"],
            "format": a.get("format"), "topics": a.get("topics", []), "audience": a.get("audience", []),
            "companies": a.get("companies", []), "big_companies": a.get("big_companies", []),
            "ai_level": a.get("ai_level", 0), "gtm_fit": a.get("gtm_fit", 0), "networking": a.get("networking", 0),
            "guests": r.get("guests") or 0, "free": bool(r.get("free")), "approval": bool(r.get("approval")), "max_price": r.get("max_price"),
            "near_stations": [f"{n} · {m} m" for n, _, m in near], "near_routes": sorted({x for _, rr, _ in near for x in rr}),
            "people": a.get("people", []), "address": r["address"], "hosts": r["hosts"]}})
    t0 = time.time()
    ok, errs = bulk(e, docs, chunk_size=20, raise_on_error=False)
    e.indices.refresh(index=EV_IDX)
    say(f"indexed {ok} events into {EV_IDX} (semantic_text embedded by Mistral inside Elastic) in {time.time() - t0:.0f}s; errors {len(errs) if isinstance(errs, list) else errs}")


# ── 3. plan ─────────────────────────────────────────────────────────────────
PERSONA_PROMPT = """Turn this person's self-description into JSON for planning ONE networking day in NYC on Thursday Oct 8 2026.
Keys: "name", "home_station" (best guess of the PATH or subway station nearest their home, e.g. "Journal Square (PATH)"),
"start_after" (HH:MM, earliest they want to leave home), "home_by" (HH:MM, latest they want to be home; early sleepers and
PATH riders should be home before trains thin out after ~21:30), "background" (short), "goals" (short),
"home_routes" (list of subway/PATH line letters or numbers at that station, e.g. ["F","G"]),
"likes" (list, e.g. running), "prefer_big_companies" (bool), "max_events" (4 or 5 — they want a full day),
"busy": list of {"from": "HH:MM", "to": "HH:MM"} blocks they cannot attend anything,
"avoid_formats": subset of ["breakfast/coffee","run/fitness","conference/summit","panel/talk","workshop","hackathon/build","dinner","happy hour/mixer","demo night","coworking"] they said they don't want,
"focus": one of "gtm","investor","builder","designer","other",
"search_queries": 4-6 natural-language searches to run against an index of tomorrow's events, each with
{"query", "after" (HH:MM), "before" (HH:MM)} covering morning, midday, afternoon and evening, phrased around what THIS person wants."""

TOOLS = [{"type": "function", "function": {
    "name": "search_events",
    "description": "Semantic search (Mistral embeddings inside Elasticsearch) over tomorrow's NYC events, filtered to a time window. "
                   "Returns candidate events with time, area, nearest stations, format, audience and companies.",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "what kind of event / people to meet"},
        "after": {"type": "string", "description": "HH:MM earliest start"},
        "before": {"type": "string", "description": "HH:MM latest start"},
        "size": {"type": "integer"}}, "required": ["query", "after", "before"]}}}]


def search_events(e, query, after="07:00", before="22:00", size=8):
    lo = dt.datetime.combine(DAY, dt.time.fromisoformat(after), NY).isoformat()
    hi = dt.datetime.combine(DAY, dt.time.fromisoformat(before), NY).isoformat()
    body = {"size": size, "_source": {"excludes": ["profile"]},
            "query": {"bool": {"must": [{"semantic": {"field": "profile", "query": query}}],
                               "filter": [{"range": {"start": {"gte": lo, "lte": hi}}}]}}}
    r = e.search(index=EV_IDX, **body)
    hits = []
    for h in r["hits"]["hits"]:
        s = h["_source"]
        hits.append({"id": h["_id"], "score": round(h["_score"], 4), "name": s["name"], "start": s["start"][11:16],
                     "end": s["end"][11:16], "area": s["area"], "format": s["format"], "audience": s["audience"],
                     "big_companies": s["big_companies"], "ai_level": s["ai_level"], "gtm_fit": s["gtm_fit"],
                     "near": s["near_stations"][:1], "summary": s["summary"]})
    return hits, body


def _t(iso):
    return dt.datetime.fromisoformat(iso).astimezone(NY)


def best_day(cands, home, start_after, home_by, max_events, prefer_big, busy=(), avoid=(), focus="other"):
    """weighted interval scheduling with travel: maximise fit - transfer/travel penalties."""
    ev = sorted(cands.values(), key=lambda x: x["start"])
    t0 = dt.datetime.combine(DAY, dt.time.fromisoformat(start_after), NY)
    tend = dt.datetime.combine(DAY, dt.time.fromisoformat(home_by), NY)

    def value(x):
        v = x["fit"] + (0.25 * x["gtm_fit"] / 3 if focus == "gtm" else 0) + 0.15 * x["ai_level"] / 3 + 0.1 * x["networking"] / 3
        v += 0.1 * math.log10((x.get("guests") or 0) + 1) / 3
        if prefer_big and x["big_companies"]:
            v += 0.25
        return v

    blocks = [(dt.datetime.combine(DAY, dt.time.fromisoformat(b["from"]), NY), dt.datetime.combine(DAY, dt.time.fromisoformat(b["to"]), NY))
              for b in busy or [] if b.get("from") and b.get("to")]

    def attend(x, arrive):
        if x.get("format") in (avoid or ()):
            return None
        s, e = _t(x["start"]), _t(x["end"])
        a = max(s, arrive)
        stay = min(e, a + dt.timedelta(minutes=150 if (e - s).total_seconds() > 4 * 3600 else 600))
        if (stay - a).total_seconds() < 45 * 60 or a > s + dt.timedelta(minutes=45):
            return None
        if any(a < b1 and stay > b0 for b0, b1 in blocks):
            return None
        return a, stay

    best = {}   # state: (idx, count) -> (score, leave_time, path)
    out = None
    for i, x in enumerate(ev):
        tr = T.trip(home, x)
        w = attend(x, t0 + dt.timedelta(minutes=tr["minutes"]))
        if w:
            best[(i, 1)] = (value(x) - 0.12 * tr["transfers"] - 0.003 * tr["minutes"], w[1], [(i, tr, w)])
    for i in range(len(ev)):
        for k in range(1, max_events):
            if (i, k) not in best:
                continue
            sc, leave, path = best[(i, k)]
            for j in range(i + 1, len(ev)):
                y = ev[j]
                tr = T.trip(ev[i], y)
                w = attend(y, leave + dt.timedelta(minutes=tr["minutes"]))
                if not w:
                    continue
                cand = (sc + value(y) - 0.12 * tr["transfers"] - 0.003 * tr["minutes"], w[1], path + [(j, tr, w)])
                if (j, k + 1) not in best or cand[0] > best[(j, k + 1)][0]:
                    best[(j, k + 1)] = cand
    for (i, k), (sc, leave, path) in best.items():
        back = T.trip(ev[i], home)
        if leave + dt.timedelta(minutes=back["minutes"]) > tend:
            continue
        tot = sc - 0.12 * back["transfers"] - 0.003 * back["minutes"]
        if out is None or tot > out[0]:
            out = (tot, path, back, leave + dt.timedelta(minutes=back["minutes"]))
    if not out:
        return None
    _, path, back, home_at = out
    legs = [{"event": ev[i], "trip_in": tr, "arrive": w[0].strftime("%H:%M"), "leave": w[1].strftime("%H:%M")} for i, tr, w in path]
    return {"legs": legs, "trip_home": back, "home_at": home_at.strftime("%H:%M"),
            "transfers": sum(l["trip_in"]["transfers"] for l in legs) + back["transfers"]}


def _norm_st(x):
    x = x.lower()
    x = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", x)
    for a, b in ((" avenue", " av"), (" ave", " av"), (" street", " st"), ("station", ""), (".", ""), ("-", " ")):
        x = x.replace(a, b)
    return re.sub(r"\s+", " ", x).strip()


def station_by_name(name, routes=()):
    n = _norm_st((name or "").split("(")[0])
    rs = set(r.upper() for r in routes or [])
    best = None
    for s in T.STATIONS:
        sn = _norm_st(s["name"].split(" (")[0])
        if n and (n == sn or n in sn or sn in n):
            score = (n == sn) * 2 + len(rs & set(s["routes"]))
            if best is None or score > best[0]:
                best = (score, s)
    if best:
        return best[1]
    return T.STATIONS[[s["name"] for s in T.STATIONS].index("Journal Square (PATH)")]


def why_not(cands, day, home, home_by):
    """the strongest candidates that did NOT make the day, and the concrete reason."""
    chosen = {l["event"]["id"] for l in day["legs"]}
    out = []
    for x in sorted(cands.values(), key=lambda x: -x["fit"]):
        if x["id"] in chosen or len(out) >= 2:
            continue
        s, e = _t(x["start"]), _t(x["end"])
        clash = next((l for l in day["legs"] if not (e <= _t(l["event"]["start"]) or s >= _t(l["event"]["end"]))), None)
        back = T.trip(x, home)
        if e + dt.timedelta(minutes=back["minutes"]) > dt.datetime.combine(DAY, dt.time.fromisoformat(home_by), NY):
            why = f"ends {e:%H:%M} — you'd be home after {home_by}"
        elif clash:
            tr = T.trip(clash["event"], x)
            why = f"overlaps {clash['event']['name'][:30]} ({tr['transfers']} transfer(s), {tr['minutes']} min apart)"
        else:
            why = f"lower fit for you (score {x['fit']:.2f})"
        out.append(f"{x['name'][:45]} — {why}")
    return out


def write_ics(day, who):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//bestday//EN"]
    for i, l in enumerate(day["legs"]):
        x = l["event"]
        a = dt.datetime.combine(DAY, dt.time.fromisoformat(l["arrive"]), NY).astimezone(dt.timezone.utc)
        b = dt.datetime.combine(DAY, dt.time.fromisoformat(l["leave"]), NY).astimezone(dt.timezone.utc)
        lines += ["BEGIN:VEVENT", f"UID:bestday-{i}-{x['id']}", f"DTSTART:{a:%Y%m%dT%H%M%SZ}", f"DTEND:{b:%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{x['name'][:70]}", f"LOCATION:{(x.get('address') or x['area'])[:90]}",
                  f"DESCRIPTION:https://luma.com/{x.get('url', '').split('/')[-1]}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    p = os.path.join(HERE, f"bestday_{re.sub(r'[^a-z]+', '_', who.lower())}.ics")
    open(p, "w").write("\r\n".join(lines))
    say(f"   📅 calendar file: {p}")


def plan(who):
    personas = json.load(open(os.path.join(HERE, "personas.json")))
    if who.strip() in personas:                      # `plan gtm` / `plan investor` / `plan builder` / `plan designer`
        say(f"persona: {personas[who.strip()]['label']}")
        who = personas[who.strip()]["who"]
    c, e = mistral(), es()
    say("① Mistral reads who you are …")
    p = jload(c.chat.complete(model=LARGE, response_format={"type": "json_object"}, temperature=0.1,
                              messages=[{"role": "system", "content": PERSONA_PROMPT},
                                        {"role": "user", "content": who}]).choices[0].message.content)
    say(json.dumps({k: p.get(k) for k in ("home_station", "start_after", "home_by", "busy", "avoid_formats", "focus", "likes")}, ensure_ascii=False))
    home_st = station_by_name(p.get("home_station"), p.get("home_routes"))
    say(f"   home station → {home_st['name']}")
    home = {"lat": home_st["lat"], "lon": home_st["lon"], "name": home_st["name"]}

    say("\n② Mistral agent decides which Elastic searches to run (function calling) …")
    msgs = [{"role": "system", "content": "You plan a networking day. Call search_events several times (morning, midday, afternoon, evening) "
                                          "to collect candidates that fit this person. Then reply DONE."},
            {"role": "user", "content": json.dumps(p, ensure_ascii=False)}]
    cands, calls = {}, []
    for _ in range(5):
        r = c.chat.complete(model=LARGE, messages=msgs, tools=TOOLS, tool_choice="auto", temperature=0.1)
        m = r.choices[0].message
        if not m.tool_calls:
            break
        msgs.append(m)
        for tc in m.tool_calls:
            a = json.loads(tc.function.arguments)
            hits, body = search_events(e, a["query"], a.get("after", "07:00"), a.get("before", "22:00"), a.get("size") or 8)
            calls.append(a)
            say(f"   search_events{json.dumps(a, ensure_ascii=False)} → {len(hits)} hits: " + " | ".join(h['name'][:28] for h in hits[:3]))
            for h in hits:
                cands.setdefault(h["id"], h)["fit"] = max(cands.get(h["id"], {}).get("fit", 0), h["score"])
            msgs.append({"role": "tool", "name": tc.function.name, "tool_call_id": tc.id,
                         "content": json.dumps([{k: h[k] for k in ("name", "start", "area", "format", "summary")} for h in hits])})
    if len(calls) < 2:     # model skipped the tools: run its own planned searches
        for q in p.get("search_queries", []):
            hits, _ = search_events(e, q["query"], q.get("after", "07:00"), q.get("before", "22:00"))
            calls.append(q)
            for h in hits:
                cands.setdefault(h["id"], h)["fit"] = max(cands.get(h["id"], {}).get("fit", 0), h["score"])
    # normalise fit and pull full docs (geo, people)
    mx = max(x["fit"] for x in cands.values()) or 1
    full = e.mget(index=EV_IDX, ids=list(cands))["docs"]
    for d in full:
        s = d["_source"]
        cands[d["_id"]].update(fit=cands[d["_id"]]["fit"] / mx, lat=s["location"]["lat"], lon=s["location"]["lon"],
                               start=s["start"], end=s["end"], networking=s["networking"], people=s["people"],
                               hosts=s.get("hosts", []), url=s["url"], address=s.get("address", ""), near_stations=s["near_stations"],
                               approval=s.get("approval"), free=s.get("free"), max_price=s.get("max_price"), guests=s.get("guests"), format=s.get("format"))
    say(f"\n③ {len(cands)} candidate events → choosing the day with the fewest transfers (subway + PATH graph from NY Open Data) …")
    day = best_day(cands, home, p.get("start_after", "07:30"), p.get("home_by", "21:30"), max(4, int(p.get("max_events", 4))), bool(p.get("prefer_big_companies")),
                   p.get("busy") or [], p.get("avoid_formats") or [], p.get("focus") or "other")
    if not day:
        say("no feasible day"); return
    for l in day["legs"]:
        x, tr = l["event"], l["trip_in"]
        how = "walk" if tr["mode"] == "walk" else f"{tr['from']} → {tr['to']} ({'one-seat' if tr['transfers'] == 0 else str(tr['transfers']) + ' transfer'})"
        say(f"   {l['arrive']}–{l['leave']}  {x['name'][:58]}  [{x['area']}]  · {tr['minutes']} min via {how}")
    th = day["trip_home"]
    say(f"   home {day['home_at']} via {th['from']} → {th['to']} · total transfers {day['transfers']}")
    for l in day["legs"]:
        x = l["event"]
        flag = ("needs host approval — request tonight" if x.get("approval") else "") + \
               ("" if x.get("free") or not x.get("max_price") else f"  ${x['max_price'] / 100:.0f}")
        if flag.strip():
            say(f"   ⚑ {x['name'][:50]}: {flag.strip()}")
    day["why_not"] = why_not(cands, day, home, p.get("home_by", "21:30"))
    for w in day["why_not"]:
        say(f"   ✗ skipped {w}")
    write_ics(day, p.get("name") or "me")

    say("\n④ Mistral writes the day …")
    brief = {"person": p, "home": home["name"], "day": [{"arrive": l["arrive"], "leave": l["leave"], "event": l["event"]["name"],
             "area": l["event"]["area"], "address": l["event"].get("address", ""), "summary": l["event"]["summary"],
             "people": l["event"].get("people", [])[:3], "hosts": l["event"].get("hosts", [])[:3],
             "getting_there": l["trip_in"]} for l in day["legs"]],
             "trip_home": day["trip_home"], "home_at": day["home_at"]}
    text = c.chat.complete(model=LARGE, temperature=0.3, messages=[
        {"role": "system", "content": "Write a tight, vivid one-day itinerary (max 230 words) for this person: for each stop give time, "
                                      "how to get there (line + transfers), why it fits them, who to talk to (only people listed, with what they do) "
                                      "and one opener line. Fill gaps with a short realistic suggestion near the next venue (e.g. a run on the "
                                      "Hudson River Greenway, breakfast at Chelsea Market) and label it 'free time'. End with the train home. "
                                      "Then add 'Follow-ups tonight:' with two short LinkedIn messages (under 300 characters) to listed people. "
                                      "Never invent people or companies."},
        {"role": "user", "content": json.dumps(brief, ensure_ascii=False)}]).choices[0].message.content
    text = text_of(text)
    say(text)
    json.dump({"persona": p, "searches": calls, "day": day, "story": text}, open(os.path.join(HERE, f"plan_{re.sub(chr(91)+chr(94)+"a-z"+chr(93)+"+", "_", (p.get("name") or "me").lower())}.json"), "w"),
              ensure_ascii=False, indent=1, default=str)


# ── 4. enterprise view ─────────────────────────────────────────────────────
def agg():
    e = es()
    r = e.search(index=EV_IDX, size=0, aggs={
        "by_format": {"terms": {"field": "format", "size": 8}},
        "gtm_audience": {"filter": {"term": {"audience": "gtm/sales"}}, "aggs": {"areas": {"terms": {"field": "area", "size": 5}}}},
        "big_cos": {"terms": {"field": "big_companies", "size": 10}},
        "ai_by_hour": {"filter": {"range": {"ai_level": {"gte": 2}}},
                       "aggs": {"h": {"date_histogram": {"field": "start", "calendar_interval": "hour", "time_zone": "America/New_York", "min_doc_count": 1}}}}})
    a = r["aggregations"]
    say("Formats:", [(b["key"], b["doc_count"]) for b in a["by_format"]["buckets"]])
    say("Where GTM people gather:", [(b["key"], b["doc_count"]) for b in a["gtm_audience"]["areas"]["buckets"]])
    say("Big companies showing up tomorrow:", [(b["key"], b["doc_count"]) for b in a["big_cos"]["buckets"]])
    say("AI-heavy events by hour:", [(b["key_as_string"][11:16], b["doc_count"]) for b in a["ai_by_hour"]["h"]["buckets"]])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"extract": extract, "index": index, "agg": agg}.get(cmd, lambda: plan(" ".join(sys.argv[2:])) if cmd == "plan" else print(__doc__))()
