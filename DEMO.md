# The Best Day for AI GTM — 3-minute demo

## Run order (terminal, from the bestday folder)
```
python3 bestday.py plan gtm        # Priscilla: the main live demo
python3 bestday.py plan investor   # quick contrast (optional, if time)
python3 bestday.py agg             # the enterprise view
```
(Data is already extracted and indexed before the demo: `extract` → `index`.)

## Talk track (≈ 3:00)

**0:00 – Hook (20 s)**
"Tomorrow, New York has 83 tech events in one day. I'm an international job seeker trying to break into AI go-to-market. I can go to maybe four. Which four, and in what order, so I don't spend my day changing trains? And I live in Jersey City, so I need to be on the PATH before the trains thin out."

**0:20 – How it works (30 s)**
"Three pieces.
One: **Mistral** reads every messy Luma event page and turns it into clean fields: format, audience, how AI-heavy it is, which big companies show up, and who the hosts are, from the page only.
Two: **Elasticsearch** stores it with a `semantic_text` field powered by a Mistral embedding inference endpoint, plus geo points. I also indexed all 496 subway stations from **NY Open Data** and the PATH stations, so every venue knows its nearest stations and lines.
Three: a **Mistral agent** reads who you are and decides which Elastic searches to run."

**0:50 – Live: `plan gtm` (75 s)**
- Point at ①: "Mistral turned my paragraph into constraints: home Journal Square, out after 7:30, home by 9:30."
- Point at ②: "Here the agent is calling Elasticsearch: morning fintech coffee, midday AI content, evening build night. Each call is a semantic search plus a time filter."
- Point at ③: "Then I choose the day like a routing problem: maximize fit, penalize every transfer and every minute on a train, and get home by 9:30. Result: [N] events, [T] transfers."
- Point at ✗: "And it tells me what it skipped and why: this one overlaps, this one would get me home after the PATH slows down."
- Point at ④: "Mistral writes the day, with who to talk to, an opener line, and follow-up LinkedIn notes for tonight. It also exports a calendar file."

**2:05 – Same city, other people (25 s)** *(optional)*
"Same index, a seed investor in Park Slope who wants breakfasts and no hackathons, gets a completely different day."

**2:30 – Enterprise view (20 s)** — run `agg`
"Flip it around. If you're an AI startup hiring SDRs, or a team deciding which event to sponsor: where do GTM people gather tomorrow, which big companies show up, and what hours are densest. That's Elastic aggregations on Mistral-extracted fields."

**2:50 – Close (10 s)**
"Mistral turns messy event pages into people, companies and constraints. Elastic turns them into a map you can query. The Best Day for AI GTM."

## What to point at if judges ask
- **Elastic:** `semantic_text` + Mistral inference endpoint (`mistral-embeddings`), `semantic` query + `range` filter, `geo_distance` sort over NY Open Data subway stations, aggregations (terms, filter, date_histogram).
- **Mistral:** `mistral-small` structured outputs (83 pages → JSON), `mistral-embed` inside Elastic, `mistral-large` function calling (agent picks the searches), final itinerary + follow-ups.
- **Transfers:** a line graph built from the stations' daytime routes; two stations under 250 m apart count as a transfer point (e.g. 33rd St PATH ↔ Herald Sq).
- **Privacy:** only public host bios from the event pages; no LinkedIn scraping.

## Devpost submission (paste)
**Name:** The Best Day for AI GTM
**Tagline:** Tell it who you are; it plans your best networking day in NYC — right events, right venues, right times, fewest transfers.
**What it does:** Mistral structures 83 NYC tech events happening on Oct 8 (format, audience, AI depth, companies, hosts). Elasticsearch indexes them with Mistral embeddings (`semantic_text`) and geo points, alongside NY Open Data subway stations and PATH stations. A Mistral agent turns a person's description into constraints and calls Elastic searches; a routing step picks the day that maximizes fit while minimizing transfers and getting you home on time. Output: an itinerary with who to meet, opener lines, skipped-and-why, follow-up messages, and a calendar file. The same index gives companies an aggregate view of where GTM talent and big-company presence concentrate.
**Built with:** Elasticsearch Serverless (semantic_text, Mistral inference endpoint, geo_distance, aggregations), Mistral (mistral-small structured outputs, mistral-embed, mistral-large function calling), NY Open Data (MTA Subway Stations), Python, Claude Code.
