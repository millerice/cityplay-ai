# CityPlay AI — Parallel Lives

**Tagline:** Your cultural taste, mapped onto the city around you — with the receipts.

---

## What it does

CityPlay AI turns a favorite musician, film, or book into grounded, nearby place
candidates. Ask *"Miles Davis — where should I look for bookshops?"* and instead
of a chatbot improvising an answer, an agent resolves the real cultural entity
through Qloo, follows its cross-domain taste associations, and returns a small
set of verifiable places on an interactive map — each with its actual source and
the reason it was kept or dropped.

The core idea is **Parallel Lives**: one input, three exploration directions.

- **The familiar you** — places matched to the interests you confirmed.
- **The adjacent you** — the agent queries Qloo for artists associated with your
  input (e.g. Miles Davis → John Coltrane), verifies that bridge is a real entity,
  and re-searches places from it, showing the two-hop *interest → cultural bridge
  → place* path.
- **The alternative you** — you supply a new starting point; the same resolution,
  checks, and evidence apply.

Every version keeps the same city center, radius, venue categories, exclusions,
and hard constraints, so the only thing that changes between them is the cultural
signal. Where two versions genuinely overlap, we show the overlap — we never
fabricate differences to make "personalization" look stronger than it is.

## Why it's agentic, not just a form

The workflow is an observable decision loop, not a prompt-and-print:

1. **Parse** — DeepSeek structures the natural-language request into an intent
   (interests, venue direction, budget/time/open-now constraints). A direct
   name-entry path keeps the core Qloo experience usable even without the model.
2. **Resolve** — the agent resolves each cultural anchor to a real Qloo entity ID,
   falling back to Qloo tags (`/v2/tags`) when a name doesn't map cleanly.
3. **Bridge** — for the adjacent version it asks Qloo for associated artists and
   re-validates the chosen bridge's entity ID before trusting it.
4. **Retrieve & check** — it queries `/search` and `/v2/insights` (with
   explainability) within the chosen venue categories, then applies category and
   coordinate checks.
5. **Present with evidence** — cards show the actual resolved anchor, Qloo source,
   and which signals were adopted; a same-category baseline is available.
6. **Re-plan** — feedback ("not for me", "too far") re-ranks or re-searches this
   session without silently widening your stated constraints.

## Why Qloo, not just an LLM

DeepSeek only structures the request. **Qloo supplies every entity ID, tag,
coordinate, and candidate** — the language model cannot invent a venue, an ID, or
a recommendation. The clearest proof is the built-in ablation: a
*same-category baseline* keeps area, venue categories, and every check fixed while
removing cultural signals, showing exactly how taste changes the result. This is
a Qloo ablation, not an LLM-only benchmark, and we don't claim the different list
is "more correct" — only that taste visibly reshapes discovery.

Real-API validation covered 20 location queries across New York and Shanghai
(25 Qloo requests, 6 website checks); the evidence report documents both the
useful candidate changes and the coverage limits.

## Built with

- **Qloo Culture API** — `/search`, `/v2/tags` (semantic), `/v2/insights` with
  explainability
- **DeepSeek** — natural-language intent structuring (model selectable in-app)
- **Python** — standard-library HTTP server, SQLite local library, threaded job
  queue with bounded Qloo pacing
- **Vanilla JS + Leaflet** — interactive map, no framework
- **Claude Code** — the whole thing was designed and built with Claude Code

## Try it

- **Live demo:** https://cityplay-ai.onrender.com/
- **Source:** https://github.com/millerice/cityplay-ai (public, MIT)

API keys are **bring-your-own**: the deployment ships with no baked-in keys. Open
the **⚙ API keys** panel (top left), pick a built-in model (DeepSeek / OpenAI /
Qwen / Kimi / GLM / Groq), and paste your Qloo + model keys. Keys stay for this
browser session (survive refresh; clear when the browser closes) and are never
written to durable storage. This is a deliberate privacy posture, not a
limitation: your credentials are not baked into the server's config.

## Honest limits

Place cards are exploration candidates. Live opening hours, event schedules,
ticket prices, booking availability, travel time, and personal satisfaction are
not guaranteed. Shanghai is experimental; New York is the primary demo area.

## What's next

Cross-session memory, itinerary/route ordering, and richer per-candidate
explainability as the Qloo insights surface more signal.
