# Rest In Pee 🚽 (R.I.P. = Restroom In Proximity)

Elastic × Mistral NYC Hack Night, Oct 7 2026.

You're on the NYC subway and need a restroom in ~10 minutes. Which stop do you get off at?

- `onboard.py` — on-the-train mode: Mistral parses the message (station, line, direction, time, minutes left); for every stop ahead (MTA GTFS schedule) Elasticsearch finds a restroom open at the minute you arrive. Total = ride + 2 min to street + walk.
- `rescue.py` — indexes 1,066 NYC Open Data public restrooms (hours normalized by Mistral) and 24/7 OpenStreetMap places into Elasticsearch; `geo_distance` + status + "open this minute" filters.
- `make_peearea.py` — Pee Area map: where you can roam and still reach an open restroom in 5–20 min, every 30 min from 7 pm to 12:30 am; free vs paid; A → B with a restroom stop.
- `bestday.py` / `transit.py` — the first idea, "The Best Day for AI GTM": plans a networking day across 83 NYC events with the fewest subway/PATH transfers.

Run: put `MISTRAL_API_KEY`, `ES_URL`, `ES_API_KEY` in `~/.hacknight.env`, then
```
python3 rescue.py index
python3 onboard.py "I got on the 1 at 50 St going downtown at 7 pm, I'll need a bathroom in 10 minutes"
python3 onboard.py coverage
```
Data: NYC Open Data Public Restrooms (i7jb-7jku), MTA Subway Stations (39hk-dx4f), MTA GTFS, OpenStreetMap (opening_hours=24/7). Built with Claude Code.
