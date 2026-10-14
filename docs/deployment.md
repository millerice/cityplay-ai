# Public demo deployment

The submission requires a publicly accessible, end-to-end application. A local
preview, screenshot, video, or static frontend without its backend is insufficient.
The repository alone does not satisfy this requirement.

## Docker/Python runtime

Use a platform that runs Docker containers behind an HTTPS reverse proxy.
Configure these **server-side** variables in the hosting platform's secret UI:

- `QLOO_API_KEY`: the hackathon credential.
- `DEEPSEEK_API_KEY`: the model credential.
- `DEEPSEEK_MODEL=deepseek-v4-pro` (or an already validated alternative).
- `PUBLIC_ORIGIN=https://your-actual-demo-host`: exact public HTTPS origin, no path.
- `PORT=8787`, or the port injected by your hosting platform.
- `CITYPLAY_QLOO_HOURLY_BUDGET=120`: bounded process-wide hourly attempts.

Do not send secrets in chat, commit them, embed them in images, or use public
frontend variables. Container builds selectively copy source/assets and exclude
`.env*`, real responses and local profiles. Runtime evidence is private to the
container and may be ephemeral. This demo has no cross-device account persistence.

Build with `docker build -t cityplay-ai .`. The container listens on `0.0.0.0`,
which requires a configured `PUBLIC_ORIGIN`. Host/Origin allowlists and CSRF stay
active. Browser cookies are Secure in public mode. `/healthz` exposes only `ok` and
can be used by a platform health check. TLS terminates at the trusted hosting proxy.

For direct Python use:

```sh
PYTHONPATH=src python3 -m cityplay.web --host 0.0.0.0
```

Use one process/replica for this demo unless session routing and shared quotas
are implemented. Limits: two concurrent jobs, 16 active sessions, six jobs/minute
per session, 40 Qloo attempts/session and the configurable process-wide hourly
budget. Process limits reset hourly; the Qloo client's monthly reserve remains.
Judge traffic and both API budgets must be checked before submission. Exceeding
limits produces explicit errors rather than fabricated recommendations.

## Acceptance before submission

1. Visit the public HTTPS URL in a fresh browser with no developer session.
2. Enter a cultural anchor and select an exploration direction; resolve real Qloo
   entities and display real candidates on the map.
3. Open the same-category baseline. Geography, filters, operational constraints,
   seen-list snapshot and validation must stay equal. The baseline still uses Qloo.
4. Verify the mobile experience, empty-result handling, and explicit upstream errors.
5. Confirm neither browser bundles nor repository contain credentials or real raw
   response records; check the root project license and third-party attribution.
6. Recheck hackathon credential validity through the judging period.

No public hosting provider or live demo URL has been selected/configured yet.
This document is deployable configuration and an acceptance plan, not a deployment claim.
