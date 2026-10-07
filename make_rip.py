"""R.I.P. — Restroom In Proximity: one-page map for the demo (rip.html)."""
import json, os
import rescue as R

H = os.path.dirname(os.path.abspath(__file__))
B = "/Users/jxy/Desktop/bestday"
SH = json.load(open(os.path.join(B, "subway_shapes.json")))
cov = json.load(open(os.path.join(H, "coverage.json")))
raw = json.load(open(os.path.join(H, "restrooms.json")))
hours = json.load(open(os.path.join(H, "restroom_hours.json")))
osm = json.load(open(os.path.join(H, "osm_24h.json")))["elements"]
TIMES = {"19:00": "7 PM", "22:00": "10 PM", "01:00": "1 AM"}


def open_at(x, t):
    h = hours.get((x.get("hours_of_operation") or "").strip()) or {}
    v = h.get("thu") if isinstance(h, dict) else None
    if not v or not v[0] or not v[1] or x.get("status") != "Operational":
        return False
    return R.mins(v[0]) <= t < R.mins(v[1])


pub = {}
for tt in TIMES:
    t = R.mins(tt)
    pub[tt] = [[float(x["latitude"]), float(x["longitude"]), x.get("facility_name", ""), x.get("location_type", "")]
               for x in raw if x.get("latitude") and open_at(x, t)]
late = []
for x in osm:
    tg = x.get("tags", {})
    kind = tg.get("amenity") or tg.get("tourism") or tg.get("shop")
    if tg.get("opening_hours") == "24/7" and kind in R.TIER and tg.get("name"):
        lat = x.get("lat") or (x.get("center") or {}).get("lat"); lon = x.get("lon") or (x.get("center") or {}).get("lon")
        late.append([lat, lon, tg["name"], R.TIER[kind][1], R.TIER[kind][0]])

stations, stats = {}, {}
for tt, rows in cov.items():
    out, n, p_ok, a_ok = [], 0, 0, 0
    for r in rows:
        ds = list(r["dirs"].values())
        n += len(ds)
        p_ok += sum(1 for d in ds if d["public"] is not None)
        a_ok += sum(1 for d in ds if d["any"] is not None)
        lvl = 2 if any(d["public"] is not None for d in ds) else (1 if any(d["any"] is not None for d in ds) else 0)
        out.append([r["lat"], r["lon"], r["name"], lvl])
    stations[tt] = out
    stats[tt] = {"free": round(100 * p_ok / n), "any": round(100 * a_ok / n), "n": n, "open_pub": len(pub[tt])}

scen = {}
for tt, f in (("19:00", "scen_19.json"), ("01:00", "scen_01.json")):
    p = os.path.join(H, f)
    if os.path.exists(p):
        scen[tt] = json.load(open(p))
scen["22:00"] = scen.get("01:00")
ORIGIN = [40.761728, -73.983849, "50 St (1)"]

D = json.dumps({"SH": SH, "pub": pub, "late": late, "st": stations, "stats": stats, "scen": scen, "origin": ORIGIN, "labels": TIMES})
page = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rest In Pee</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--ink:#16161a;--mute:#6c6c75;--line:#e5e2dc;--free:#2f9e44;--paid:#f08c00;--dead:#e03131;--m:#fa520f;--e:#00a9a5}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif;background:#f6f4ef;color:var(--ink)}
header{display:flex;justify-content:space-between;align-items:flex-end;padding:18px 26px 8px;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:32px;letter-spacing:-.02em}h1 small{font-size:15px;color:var(--mute);font-weight:500;margin-left:8px}
.tabs button{border:1px solid var(--line);background:#fff;padding:9px 18px;border-radius:999px;font-size:15px;cursor:pointer;margin-left:6px}
.tabs button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
main{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;padding:6px 26px 18px;height:calc(100vh - 92px)}
#map{border-radius:16px;border:1px solid var(--line);height:100%}
.side{overflow:auto}
.big{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin-bottom:12px}
.big .n{font-size:54px;font-weight:800;line-height:1}.big .l{color:var(--mute);font-size:14px;margin-top:4px}
.row{display:flex;gap:10px}.row .big{flex:1}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px 16px;margin-bottom:12px;font-size:14.5px;line-height:1.5}
.card h3{margin:0 0 6px;font-size:16px}.step{margin:4px 0}.tag{display:inline-block;border-radius:6px;padding:1px 7px;font-size:12px;color:#fff}
.leg{display:flex;gap:10px;font-size:12.5px;color:var(--mute);flex-wrap:wrap;margin-top:6px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:-1px}
.tech{display:grid;grid-template-columns:1fr 1fr;gap:10px}.tech div{border-radius:12px;padding:10px 12px;color:#fff;font-size:12.5px;line-height:1.45}
.tech b{font-size:14px}
</style></head><body>
<header><h1>Rest In Pee 🚽 <small>R.I.P. = Restroom In Proximity · you're on the subway, you have 10 minutes</small></h1>
<div class="tabs" id="tabs"></div></header>
<main><div id="map"></div><div class="side" id="side"></div></main>
<script>
const D=__D__;
const map=L.map('map').setView([40.758,-73.975],13);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Esri · MTA GTFS · NYC Open Data · OpenStreetMap'}).addTo(map);
D.SH.forEach(l=>{L.polyline(l.p,{color:l.c,weight:3,opacity:.55}).addTo(map);
  const name=l.r.replace('GS','S').replace('FS','S').replace('SI','SIR');
  [0.35,0.7].forEach(f=>{const q=l.p[Math.floor(l.p.length*f)];
   L.marker(q,{interactive:false,icon:L.divIcon({className:'',iconSize:[16,16],html:`<div style="width:16px;height:16px;border-radius:50%;background:${l.c};color:${['N','Q','R','W'].includes(name)?'#000':'#fff'};font:700 10px/16px Helvetica;text-align:center;box-shadow:0 0 0 2px #fff">${name}</div>`})}).addTo(map)})});
let lay=L.layerGroup().addTo(map);
const C=['#e03131','#f08c00','#2f9e44'];
const ic=(e,s)=>L.divIcon({className:'',iconSize:[s,s],html:`<div style="font-size:${s}px;line-height:1">${e}</div>`});
function show(tt){
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===tt));
  lay.clearLayers();
  D.st[tt].forEach(s=>L.circleMarker([s[0],s[1]],{radius:5,weight:1.5,color:'#fff',fillColor:C[s[3]],fillOpacity:.95})
     .bindTooltip(s[2]+(s[3]==2?' · free restroom ≤10 min':s[3]==1?' · only pay-to-pee 24/7 places ≤10 min':' · nothing ≤10 min')).addTo(lay));
  D.pub[tt].forEach(p=>L.marker([p[0],p[1]],{icon:ic('🚻',15)}).bindTooltip(p[2]+' · '+p[3]+' · free, open now').addTo(lay));
  if(tt!=='19:00') D.late.forEach(p=>L.circleMarker([p[0],p[1]],{radius:3,color:p[4]==1?'#2f9e44':'#f08c00',weight:1,fillOpacity:.7}).bindTooltip(p[2]+' · '+p[3]).addTo(lay));
  const sc=D.scen[tt]; let card='';
  if(sc){const b=sc.best;
    L.marker([D.origin[0],D.origin[1]],{icon:ic('🚇',24)}).bindTooltip('You board: '+D.origin[2],{permanent:true,direction:'left'}).addTo(lay);
    L.polyline([[D.origin[0],D.origin[1]],[b.slat,b.slon]],{color:'#ee352e',weight:7,opacity:.85}).addTo(lay);
    L.polyline([[b.slat,b.slon],[b.rlat,b.rlon]],{color:'#16161a',weight:4,dashArray:'4 6'}).addTo(lay);
    L.marker([b.rlat,b.rlon],{icon:ic('🚽',30)}).bindTooltip(b.restroom,{permanent:true,direction:'right'}).addTo(lay);
    map.fitBounds(L.latLngBounds([[D.origin[0],D.origin[1]],[b.slat,b.slon],[b.rlat,b.rlon]]).pad(0.9));
    const free=b.kind==='public';
    card=`<div class="card"><h3>🚇 "${sc.msg}"</h3>
      <div class="step">① <b>Mistral</b> → station <b>50 St</b>, line <b>1</b>, <b>downtown</b>, <b>${sc.parsed.time}</b>, <b>${sc.parsed.minutes_left} min</b></div>
      <div class="step">② <b>MTA schedule</b> × <b>Elastic</b>: every stop ahead → restrooms open the minute you arrive</div>
      <div class="step">③ ${b.stops?`Stay on <b>${b.stops} stop${b.stops>1?'s':''}</b>, get off at`:'Get off at'} <b>${b.get_off_name}</b> · ${b.ride} min ride + 2 min to street + ${b.walk} min walk</div>
      <div class="step" style="font-size:17px;margin-top:6px">🚽 <b>${b.restroom}</b> <span class="tag" style="background:${free?'var(--free)':'var(--paid)'}">${free?'FREE':'buy something'}</span> · <b>${b.total} min</b></div>
      ${(sc.alts||[]).slice(0,2).map(a=>`<div class="leg">alt · ${a.get_off_name} → ${a.restroom} (${a.kind==='public'?'free':'24/7, buy something'}) ≈ ${a.total} min</div>`).join('')}</div>`;}
  else map.setView([40.758,-73.975],13);
  const s=D.stats[tt];
  document.getElementById('side').innerHTML=`
   <div class="row"><div class="big"><div class="n" style="color:${s.free?'var(--free)':'var(--dead)'}">${s.free}%</div><div class="l">of Manhattan riders (${s.n} station-directions) can reach a <b>free</b> public restroom within 10 min at ${D.labels[tt]}</div></div>
   <div class="big"><div class="n">${s.open_pub}</div><div class="l">public restrooms open citywide at ${D.labels[tt]}</div></div></div>
   ${card}
   <div class="leg"><span><span class="dot" style="background:var(--free)"></span>free restroom ≤10 min</span><span><span class="dot" style="background:var(--paid)"></span>only 24/7 pay-to-pee</span><span><span class="dot" style="background:var(--dead)"></span>R.I.P.</span><span>🚻 public restroom open now</span></div>
   <div class="tech" style="margin-top:12px"><div style="background:var(--m)"><b>Mistral</b><br>reads your message (station, line, direction, time, minutes left)<br>normalizes 146 messy opening-hours formats into open/close per day</div>
   <div style="background:var(--e)"><b>Elasticsearch</b><br>geo_distance + status + "open this minute" filters over 1,066 NYC Open Data restrooms; 24/7 fallback over 170 OpenStreetMap places; every stop ahead from the MTA schedule</div></div>`;
}
Object.keys(D.labels).forEach(t=>{const b=document.createElement('button');b.textContent=D.labels[t];b.dataset.t=t;b.onclick=()=>show(t);document.getElementById('tabs').appendChild(b)});
show('19:00');
</script></body></html>"""
open(os.path.join(H, "rip.html"), "w").write(page.replace("__D__", D))
print("wrote rip.html", {k: v for k, v in stats.items()})
