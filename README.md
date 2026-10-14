# CityPlay AI

**From your cultural taste to a different side of the city.**

CityPlay AI is a Qloo-powered agentic workflow: a favorite musician, film, book or
concept becomes real place candidates in an explicitly selected area. DeepSeek
structures the request; Qloo resolves cultural anchors and grounds cross-domain
recommendations. The model never invents venue IDs, coordinates or recommendation
records. New York is the verified primary demo area; Shanghai is experimental.

## Try it

The public demo URL is pending hosting configuration. Until it is deployed and
verified, this project is **not yet ready for submission**.

Local preview requires Python 3.12+:

```sh
cp .env.example .env.local
# Privately set QLOO_API_KEY and DEEPSEEK_API_KEY in .env.local.
PYTHONPATH=src python3 -m cityplay.web --port 8787
```

Open http://127.0.0.1:8787/. No registration is required. Try a concrete cultural
anchor plus a venue direction, such as Miles Davis and bookshops or Blade Runner
and coffee. The optional interest wizard can help with input, but is never required.

## What makes it Qloo-powered

1. Resolve public entities and concepts with `/search` and `/v2/tags`.
2. Query `/v2/insights` using the cultural signals, area and venue tags.
3. Check actual categories, coordinates, addresses and user exclusions.
4. Present a few candidates, actual resolved anchors, a map and verification status.
5. Handle candidate ambiguity and missing signals with bounded, visible adjustments.

An optional **same-category baseline** removes cultural signals while preserving
filters, area, constraints, seen-list snapshot and checks. It is still Qloo-powered;
it is not an LLM-only test. A different list does not prove improved satisfaction.

Removing Qloo removes the grounded candidate source. There is no fabricated
fallback when authentication, quota or network calls fail. Website names can be
corroborated, but live hours, branch access, prices, events and route times remain
unverified unless independently established. Explicit operational constraints
continue to block unsupported promises.

## Run and validate

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -q
node tests/test_exploration_policy.cjs
```

Tests use clearly synthetic data and do not consume API quota. Live capability
validation (up to 30 Qloo attempts) can be repeated with:

```sh
PYTHONPATH=src python3 scripts/validate_cityplay_value.py
```

The [data-value report](docs/cityplay-data-value-report.md) documents real aggregate
results and limitations. Other evidence: [Qloo capability report](docs/qloo-capability-report.md),
[coordinate validation](docs/leaflet-coordinate-validation.md),
[interest wizard](docs/guess-my-interests.md).

## Deploy publicly

See [Docker/Python deployment](docs/deployment.md) and the
[submission description](docs/submission-description.md).

The Docker image contains source and assets, never credentials. Configure keys
privately on the selected host, serve through HTTPS and set `PUBLIC_ORIGIN`.
A static frontend or local URL does not satisfy the competition's demo requirement.

## Data and licenses

Credentials stay server-side. The local `APIKey` alias for Qloo is also accepted.
Raw responses, private drafts and confirmation records are retained only in
`.qloo-private/` and excluded from Git and Docker. Fixtures are synthetic.
Real Qloo records must not be committed or publicly distributed as datasets.

Project code is [MIT licensed](LICENSE); see [third-party notices](THIRD_PARTY_NOTICES.md)
for Leaflet and OpenStreetMap attribution. Map coordinates use original Qloo
latitude/longitude; datum and entrance-position accuracy remain unverified.
