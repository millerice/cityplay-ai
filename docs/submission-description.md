# CityPlay AI — Cultural taste becomes city discovery

CityPlay AI is an agentic cultural-discovery workflow that turns a favorite
musician, film, book, or taste concept into grounded place candidates nearby.
Users review one short plan, then the agent resolves cultural entities through
Qloo, queries cross-domain taste associations within the chosen venue direction,
checks category and coordinate constraints, and presents a few traceable
candidates on an interactive map.

DeepSeek structures the request. Qloo supplies the actual taste signals and
place candidates; the language model cannot invent venue IDs, coordinates or
recommendations. The agent handles bounded candidate matching and explains what
it adopted or skipped. Users can inspect actual resolved anchors, sources and
verification limits, then revise their cultural input and explore again.

An optional same-category baseline keeps the area, venue constraints and checks
fixed while removing cultural signals. It shows how taste changes discovery,
without claiming that a different list proves better personal satisfaction.
This is a Qloo ablation, not an LLM-only benchmark.

Real API validation covered 20 location queries across New York and Shanghai,
with 25 total Qloo requests and six website checks. New York is the primary demo
area; Shanghai remains experimental. The evidence report documents both the
useful candidate changes and geographic/category coverage limitations.

Place cards are exploration candidates. Live opening hours, event schedules,
ticket prices, booking availability, travel time and personal satisfaction are
not guaranteed. Website-name matches are shown independently of cultural ranking.

## Submission links

- Public source repository: https://github.com/millerice/cityplay-ai (public, MIT).
- Live, externally hosted demo: pending hosting configuration and end-to-end verification.

A locally running preview or video does not fulfill the demo requirement.
