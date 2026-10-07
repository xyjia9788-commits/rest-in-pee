"""Pee Area: where can you roam and still reach an open restroom within N minutes? Free vs paid plans, per station."""
import json, math, os, re
import rescue as R

H = os.path.dirname(os.path.abspath(__file__))
SH = json.load(open("/Users/jxy/Desktop/bestday/subway_shapes.json"))
raw = json.load(open(os.path.join(H, "restrooms.json")))
hours = json.load(open(os.path.join(H, "restroom_hours.json")))
osm = json.load(open(os.path.join(H, "osm_24h.json")))["elements"]
mta = json.load(open(os.path.join(H, "mta_stations.json")))
TIMES = {f"{h % 24:02d}:{m:02d}": f"{(h - 1) % 12 + 1}:{m:02d} {'PM' if h < 24 else 'AM'}" for h in range(19, 25) for m in (0, 30)}
WALK = 80  # m per minute
SPEND = {"fast_food": "≈ $1–3 · cheapest drink (restroom code often on the receipt)", "cafe": "≈ $3–5 · a coffee", "restaurant": "≈ $3–5 · coffee or soda at a diner",
         "hotel": "$0 · ask the front desk (not guaranteed)", "hospital": "$0 · ER waiting room", "ferry_terminal": "$0 · public terminal"}


def km(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def open_at(x, t):
    h = hours.get((x.get("hours_of_operation") or "").strip()) or {}
    v = h.get("thu") if isinstance(h, dict) else None
    return bool(v and v[0] and v[1] and x.get("status") == "Operational" and R.mins(v[0]) <= t < R.mins(v[1]))


paid, free247 = [], []
for x in osm:
    tg = x.get("tags", {})
    kind = tg.get("amenity") or tg.get("tourism") or tg.get("shop")
    if tg.get("opening_hours") == "24/7" and kind in SPEND and tg.get("name") and not re.search(r"dunkin|krispy kreme", tg["name"], re.I):
        lat = x.get("lat") or (x.get("center") or {}).get("lat"); lon = x.get("lon") or (x.get("center") or {}).get("lon")
        rec = [lat, lon, tg["name"], SPEND[kind]]
        if kind == "hospital":
            continue                      # 10/7 她定：急诊等候室不算
        (free247 if kind == "ferry_terminal" else paid).append(rec)

FREE = {}
for tt in TIMES:
    t = R.mins(tt)
    FREE[tt] = [[float(x["latitude"]), float(x["longitude"]), x.get("facility_name", ""), "$0 · public restroom"]
                for x in raw if x.get("latitude") and open_at(x, t)] + free247
STN = [[float(s["gtfs_latitude"]), float(s["gtfs_longitude"]), f"{s['stop_name']} ({s['daytime_routes'].replace(' ', '/')})"]
       for s in mta if s["borough"] == "M"]
D = json.dumps({"SH": SH, "FREE": FREE, "PAID": paid, "STN": STN, "labels": TIMES})
print({k: len(v) for k, v in FREE.items()}, "paid", len(paid))

page = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pee Area</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{--ink:#16161a;--mute:#6c6c75;--line:#e5e2dc;--free:#2f9e44;--paid:#f08c00;--dead:#e03131}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif;background:#f6f4ef;color:var(--ink)}
header{padding:16px 24px 6px;display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px}
h1{margin:0;font-size:30px}h1 small{font-size:14px;color:var(--mute);font-weight:500;margin-left:8px}
.ctl{display:flex;gap:14px;flex-wrap:wrap}.grp{display:flex;gap:4px;background:#fff;border:1px solid var(--line);border-radius:999px;padding:3px}
.grp button{border:0;background:none;padding:7px 13px;border-radius:999px;font-size:14px;cursor:pointer}.grp button.on{background:var(--ink);color:#fff}
main{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;padding:6px 24px 16px;height:calc(100vh - 130px)}
#map{border-radius:16px;border:1px solid var(--line);height:100%}.side{overflow:auto}
.big{background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 14px;margin-bottom:10px;flex:1}
.big .n{font-size:44px;font-weight:800;line-height:1}.big .l{color:var(--mute);font-size:13px;margin-top:4px}.row{display:flex;gap:10px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 14px;margin-bottom:10px;font-size:14px;line-height:1.5}
.card h3{margin:0 0 6px;font-size:16px}.tag{border-radius:6px;padding:1px 7px;font-size:12px;color:#fff}
.hint{color:var(--mute);font-size:13px}
</style></head><body>
<header><h1>Pee Area 🚽 <small>where you can roam and still make it to an open restroom</small></h1>
<div class="ctl"><div class="grp" id="gm"></div><div class="grp" id="gp"></div><div class="grp" id="gb"></div></div></header>
<div style="padding:0 24px"><div class="grp" id="gt" style="display:inline-flex;flex-wrap:wrap"></div></div>
<main><div id="map"></div><div class="side" id="side"></div></main>
<script>
const D=__D__;
let T='22:00',B=10,PLAN='both',SEL=null,MODE='station',A=null,Bp=null;
const map=L.map('map').setView([40.758,-73.975],13);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Esri · MTA GTFS · NYC Open Data · OpenStreetMap'}).addTo(map);
D.SH.forEach(l=>L.polyline(l.p,{color:l.c,weight:2.5,opacity:.5}).addTo(map));
const area=L.layerGroup().addTo(map), sts=L.layerGroup().addTo(map), sel=L.layerGroup().addTo(map);
const em=(e,s)=>L.divIcon({className:'',iconSize:[s,s],html:`<div style="font-size:${s}px;line-height:1">${e}</div>`});
const km=(a,b,c,d)=>{const r=Math.PI/180,p1=a*r,p2=c*r,h=Math.sin((p2-p1)/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin((d-b)*r/2)**2;return 12742*Math.asin(Math.sqrt(h))};
const mins=k=>Math.max(1,Math.round(k*1000/80));
function near(lat,lon,list){let best=null;list.forEach(p=>{const d=km(lat,lon,p[0],p[1]);if(!best||d<best.d)best={d,p}});return best&&{name:best.p[2],spend:best.p[3],lat:best.p[0],lon:best.p[1],min:mins(best.d)}}
const lists=()=>PLAN==='free'?[['free',D.FREE[T]]]:PLAN==='paid'?[['paid',D.PAID]]:[['free',D.FREE[T]],['paid',D.PAID]];
function btns(id,opts,cur,fn){const g=document.getElementById(id);g.innerHTML='';opts.forEach(([v,t])=>{const b=document.createElement('button');b.textContent=t;b.className=v==cur?'on':'';b.onclick=()=>fn(v);g.appendChild(b)})}
function draw(){
  btns('gt',Object.entries(D.labels),T,v=>{T=v;draw()});
  btns('gb',[5,10,15,20].map(m=>[m,m+' min'+(m==5?' · urgent':m==20?' · max night':'')]),B,v=>{B=+v;draw()});
  btns('gp',[['free','Free'],['paid','Paid'],['both','Both']],PLAN,v=>{PLAN=v;draw()});
  btns('gm',[['station','Station'],['ab','A → B + 🚽']],MODE,v=>{MODE=v;A=null;Bp=null;SEL=null;draw()});
  area.clearLayers();sts.clearLayers();
  const r=B*80, op=.18-B*0.004;
  if(PLAN!=='free') D.PAID.forEach(p=>L.circle([p[0],p[1]],{radius:r,stroke:false,fillColor:'#f08c00',fillOpacity:op*.7}).addTo(area));
  if(PLAN!=='paid'){D.FREE[T].forEach(p=>L.circle([p[0],p[1]],{radius:r,stroke:false,fillColor:'#2f9e44',fillOpacity:op}).addTo(area));
    D.FREE[T].forEach(p=>L.marker([p[0],p[1]],{icon:em('🚻',13)}).bindTooltip(p[2]+' · '+p[3]).addTo(area));}
  let nf=0,np=0;
  D.STN.forEach((s,i)=>{const f=near(s[0],s[1],D.FREE[T]),p=near(s[0],s[1],D.PAID);
    const fo=f&&f.min<=B,po=p&&p.min<=B;nf+=fo;np+=po;
    const ok=PLAN==='free'?fo:PLAN==='paid'?po:(fo||po);
    const col=!ok?'#e03131':(fo&&PLAN!=='paid'?'#2f9e44':'#f08c00');
    L.circleMarker([s[0],s[1]],{radius:5.5,weight:1.5,color:'#fff',fillColor:col,fillOpacity:1}).bindTooltip(s[2])
     .on('click',e=>{L.DomEvent.stopPropagation(e);if(MODE==='station'){SEL=i;card()}else pick(s[0],s[1],s[2])}).addTo(sts)});
  const n=D.STN.length,pct=x=>Math.round(100*x/n);
  document.getElementById('side').innerHTML=`<div class="row">
    <div class="big"><div class="n" style="color:${nf?'var(--free)':'var(--dead)'}">${pct(nf)}%</div><div class="l">of Manhattan stations: <b>free</b> public restroom within <b>${B} min</b> walk at ${D.labels[T]} (${D.FREE[T].length} open citywide)</div></div>
    <div class="big"><div class="n" style="color:var(--paid)">${pct(np)}%</div><div class="l"><b>paid</b> option (buy the cheapest drink) within ${B} min</div></div></div>
    <div id="card"></div>
    <div class="hint">${MODE==='ab'?'Click point <b>A</b> on the map, then point <b>B</b> (anywhere, or a station).':'Click any station.'} Green = free pee area · Orange = paid · Red stations = R.I.P.</div>
    <div class="card" style="margin-top:10px"><b>How it works</b><br>Free = NYC Open Data public restrooms (+ Staten Island Ferry terminal), opening hours normalized by <b>Mistral</b>, filtered to "open at ${D.labels[T]}". ER waiting rooms are not counted.<br>
    Paid = 24/7 places from OpenStreetMap with an estimated minimum spend.<br>The live "open now + nearby" queries run in <b>Elasticsearch</b> (geo_distance + hours filters).</div>`;
  card();
}
function card(){
  sel.clearLayers();const el=document.getElementById('card');if(!el)return;
  if(MODE==='ab'){abCard();return}
  if(SEL===null){el.innerHTML='';return}
  const s=D.STN[SEL],f=near(s[0],s[1],D.FREE[T]),p=near(s[0],s[1],D.PAID);
  const line=(x,kind)=>x?`<div>${kind==='free'?'<span class="tag" style="background:var(--free)">FREE</span>':'<span class="tag" style="background:var(--paid)">PAID</span>'} <b>${x.name}</b> · <b>${x.min} min</b> walk ${x.min<=B?'✅':'⚠️ over '+B+' min'}<br><span class="hint">${x.spend}</span></div>`:`<div>${kind}: nothing open</div>`;
  el.innerHTML=`<div class="card"><h3>🚇 ${s[2]} · ${D.labels[T]}</h3>${PLAN!=='paid'?line(f,'free'):''}<div style="height:6px"></div>${PLAN!=='free'?line(p,'paid'):''}</div>`;
  [[f,'#2f9e44','🚽'],[p,'#f08c00','🥤']].forEach(([x,c,e],k)=>{if(x&&(k?PLAN!=='free':PLAN!=='paid')){L.polyline([[s[0],s[1]],[x.lat,x.lon]],{color:c,weight:4,dashArray:'4 6'}).addTo(sel);L.marker([x.lat,x.lon],{icon:em(e,24)}).addTo(sel)}});
  L.circle([s[0],s[1]],{radius:B*80,color:'#16161a',weight:1.5,fill:false,dashArray:'3 5'}).addTo(sel);
}
function pick(lat,lon,name){ if(!A||Bp){A=[lat,lon,name||'A'];Bp=null}else Bp=[lat,lon,name||'B']; card() }
map.on('click',e=>{if(MODE==='ab')pick(e.latlng.lat,e.latlng.lng)});
function abCard(){
  const el=document.getElementById('card');
  if(A)L.marker([A[0],A[1]],{icon:em('🅰️',24)}).addTo(sel);
  if(!A||!Bp){el.innerHTML=`<div class="card"><h3>A → B with a restroom stop</h3>${A?'Now click <b>B</b>.':'Click <b>A</b>.'}</div>`;return}
  L.marker([Bp[0],Bp[1]],{icon:em('🅱️',24)}).addTo(sel);
  const direct=mins(km(A[0],A[1],Bp[0],Bp[1]));
  const best=(list)=>{let b=null;list.forEach(p=>{const d=km(A[0],A[1],p[0],p[1]),d2=km(p[0],p[1],Bp[0],Bp[1]);if(!b||d+d2<b.t)b={t:d+d2,a:d,p}});return b&&{name:b.p[2],spend:b.p[3],lat:b.p[0],lon:b.p[1],toR:mins(b.a),total:mins(b.t)}};
  let h=`<div class="card"><h3>${A[2]} → ${Bp[2]} · ${D.labels[T]}</h3>Direct walk: <b>${direct} min</b>`;
  lists().forEach(([k,list])=>{const r=best(list);if(!r){h+=`<div>${k}: nothing open</div>`;return}
    const c=k==='free'?'#2f9e44':'#f08c00';
    L.polyline([[A[0],A[1]],[r.lat,r.lon],[Bp[0],Bp[1]]],{color:c,weight:4,dashArray:'5 6'}).addTo(sel);
    L.marker([r.lat,r.lon],{icon:em(k==='free'?'🚽':'🥤',24)}).addTo(sel);
    h+=`<div style="margin-top:6px"><span class="tag" style="background:${c}">${k.toUpperCase()}</span> via <b>${r.name}</b>: 🚽 in <b>${r.toR} min</b> ${r.toR<=B?'✅':'⚠️ over '+B}, total <b>${r.total} min</b> (+${r.total-direct} detour)<br><span class="hint">${r.spend}</span></div>`});
  el.innerHTML=h+`<div class="hint" style="margin-top:6px">Long trips: ride the subway and use the station view at the stop where you get off.</div></div>`;
}
draw();
</script></body></html>"""
open(os.path.join(H, "peearea.html"), "w").write(page.replace("__D__", D))
print("wrote peearea.html")
