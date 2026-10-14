"""Loopback-only Web MVP. python -m cityplay.web --port 8787

Static allowlist, browser-bound sessions and jobs; credentials remain server-side.
This is a local development service, not a public production deployment.
"""
import argparse
import copy
from dataclasses import asdict, dataclass, field
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import secrets
import threading
import time
import urllib.parse
import uuid

from .__main__ import save_private
from .config import ROOT, Settings
from .engine import DiscoveryEngine, distance_m
from .intent import Area, Intent, ModelIntentParser
from .transport import DeepSeekClient, QlooClient, ServiceError, network
from .verify import WebsiteVerifier
from .profile import validate_answers, generate, confirm

PRESETS = {
    "new_york": {"lat": 40.722668, "lon": -73.99823, "label": "纽约下城示例中心"},
    # 31°14′ N, 121°29′ E; public Shanghai Basic Facts, not private Qloo data.
    "shanghai": {"lat": 31 + 14/60, "lon": 121 + 29/60, "label": "上海示例中心 · 实验支持"},
}
STATIC = {"/map.js": ("map.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css; charset=utf-8"),"/guess.js": ("guess.js", "text/javascript; charset=utf-8"),"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


@dataclass
class Session:
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    draft_id: str | None = None
    intent: dict | None = None
    city: str | None = None
    area: dict | None = None
    confirmed: dict | None = None
    shown: set = field(default_factory=set)
    comparison_seen: list = field(default_factory=list)
    selections: dict = field(default_factory=dict)
    busy: bool = False
    jobs: dict = field(default_factory=dict)
    submissions: list = field(default_factory=list)
    qloo: object = None
    verifier: object = None
    independent_bookstore: bool = False
    profile_draft: dict | None = None
    profile_draft_id: str | None = None
    profile_confirmed: dict | None = None
    profile_receipt: dict | None = None


class Application:
    def __init__(self, settings=None, *, model_factory=None, qloo_factory=None, verifier_factory=None,
                 evidence_dir=None, process_budget=120, budget_window_seconds=3600):
        self.settings = settings or Settings.load()
        self.model_factory = model_factory or (lambda: DeepSeekClient(self.settings.deepseek_key, self.settings.model))
        self.qloo_factory = qloo_factory or (lambda: QlooClient(self.settings.qloo_key, sender=self.qloo_network, max_calls=40))
        self.verifier_factory = verifier_factory or (lambda: WebsiteVerifier(max_checks=12))
        self.evidence_dir = evidence_dir or ROOT / ".qloo-private" / "stage3"
        self.sessions, self.lock = {}, threading.RLock()
        self.slots = threading.BoundedSemaphore(2)
        self.network_lock = threading.Lock()
        if process_budget <= 0 or budget_window_seconds <= 0:
            raise ValueError("Invalid process budget")
        self.network_calls, self.process_budget, self.last_network = 0, process_budget, 0.0
        self.budget_window_seconds = budget_window_seconds
        self.network_window_started = time.monotonic()

    def qloo_network(self, *args, **kwargs):
        # All browser sessions share a process-wide budget and API pacing.
        with self.network_lock:
            if time.monotonic()-self.network_window_started >= self.budget_window_seconds:
                self.network_calls = 0
                self.network_window_started = time.monotonic()
            if self.network_calls >= self.process_budget:
                raise ServiceError("WEB_PROCESS_BUDGET_EXHAUSTED")
            time.sleep(max(0, 0.3 - (time.monotonic()-self.last_network)))
            self.last_network = time.monotonic()
            self.network_calls += 1
        return network(*args, **kwargs)

    def session(self, identifier=None, create=False):
        with self.lock:
            now = time.monotonic()
            for key in list(self.sessions):
                if now-self.sessions[key].touched > 1800 and not self.sessions[key].busy:
                    del self.sessions[key]
            existing = self.sessions.get(identifier)
            if existing:
                existing.touched = now
                return identifier, existing
            if not create or len(self.sessions) >= 16:
                return None, None
            identifier = secrets.token_urlsafe(32)
            value = Session(qloo=self.qloo_factory(), verifier=self.verifier_factory())
            self.sessions[identifier] = value
            return identifier, value

    def start(self, session, kind, payload):
        with self.lock:
            now = time.monotonic()
            session.submissions = [x for x in session.submissions if now-x < 60]
            if session.busy:
                raise ServiceError("JOB_ALREADY_RUNNING", status=409)
            if len(session.submissions) >= 6:
                raise ServiceError("LOCAL_REQUEST_LIMIT", status=429)
            if not self.slots.acquire(blocking=False):
                raise ServiceError("LOCAL_SERVICE_BUSY", retryable=True, status=429)
            session.busy = True
            session.submissions.append(now)
            identifier = str(uuid.uuid4())
            session.jobs[identifier] = {"job_id": identifier, "kind": kind, "status": "running", "progress": "PARSING" if kind == "parse" else "INTENT_PARSED"}
            # Bound retained browser results in memory.
            while len(session.jobs) > 20:
                del session.jobs[next(iter(session.jobs))]
            threading.Thread(target=self.worker, args=(session, identifier, kind, payload), daemon=True).start()
            return identifier

    def worker(self, session, identifier, kind, payload):
        model_trace = []
        completion = None
        def fail(error):
            nonlocal completion
            completion = {"status": "failed", "error": error}
            try:
                save_private(self.evidence_dir / (identifier + ".error.json"),
                             {"job_id": identifier, "kind": kind, "status": "failed", "error": error}, self.settings)
            except (ValueError, OSError):
                pass
        try:
            if kind == "guess":
                answers = validate_answers(payload["answers"], (self.settings.qloo_key, self.settings.deepseek_key))
                model = self.model_factory()
                model.max_tokens = 2600
                profile = generate(model, answers)
                with self.lock:
                    session.profile_draft = profile
                    session.profile_draft_id = str(uuid.uuid4())
                    session.profile_receipt = None
                result = {"draft_id": session.profile_draft_id, "profile": profile, "status": "draft"}
            elif kind == "parse":
                query = payload.get("query")
                city = payload.get("city")
                if city not in PRESETS:
                    raise ValueError("Unsupported city")
                area = Area(**payload["area"])
                if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
                    raise ValueError("Invalid query")
                if any(secret and secret in query for secret in [self.settings.qloo_key, self.settings.deepseek_key]) or re.search(r"\S+@\S+|\d{10,}", query):
                    raise ServiceError("SENSITIVE_INPUT_REJECTED", status=400)
                self.validate_area(city, area)
                model = self.model_factory()
                city_context = "纽约附近" if city == "new_york" else "上海附近"
                intent = ModelIntentParser(model).parse(query + "\n页面上明确选择的探索区域：" + city_context)
                model_trace = model.trace
                if intent.city != city:
                    intent.clarifications.append("The requested city differs from the selected area; choose a matching area.")
                values = asdict(intent)
                values.pop("parser", None)
                with self.lock:
                    session.draft_id, session.intent = str(uuid.uuid4()), values
                    session.area, session.city = asdict(area), city
                    session.independent_bookstore = bool(re.search(r"independent book|indie book|独立书店", query, re.I))
                    session.confirmed, session.shown, session.selections = None, set(), {}
                result = {"status": "needs_confirmation", "draft_id": session.draft_id, "intent": values,
                          "city": city, "area": asdict(area), "model": model.model}
            elif kind == "compare":
                result = self.compare(session, payload)
            else:
                result = self.discover(session, payload, identifier)
            evidence = {"job_id": identifier, "kind": kind, "result": result, "model_tools": model_trace}
            if kind != "guess":
                save_private(self.evidence_dir / (identifier + ".json"), evidence, self.settings)
            completion = {"status": "completed", "progress": "DONE", "result": result}
        except ServiceError as error:
            fail({"code": error.code, "retryable": error.retryable, "http_status": error.status, **({"details": error.details} if error.details else {})})
        except (ValueError, TypeError, KeyError, OSError):
            fail({"code": "INVALID_INPUT_OR_LOCAL_STATE", "retryable": False})
        except Exception:
            # Do not emit tracebacks which could include upstream data or credentials.
            fail({"code": "INTERNAL_ERROR", "retryable": False})
        finally:
            with self.lock:
                session.busy = False
                self.slots.release()
                # Terminal state and availability become visible atomically.
                session.jobs[identifier].update(completion or {"status": "failed", "error": {"code": "INTERNAL_ERROR"}})

    def confirm_profile(self, session, payload):
        with self.lock:
            if session.busy:
                raise ServiceError("JOB_ALREADY_RUNNING", status=409)
            if payload.get("draft_id") != session.profile_draft_id or not session.profile_draft:
                raise ServiceError("DRAFT_EXPIRED", status=409)
            if session.profile_receipt:
                if payload == session.profile_receipt["payload"]:
                    return session.profile_receipt["result"]
                raise ServiceError("PROFILE_ALREADY_CONFIRMED", status=409)
            profile, merged = confirm(session.profile_draft, payload, (self.settings.qloo_key, self.settings.deepseek_key))
            identifier = str(uuid.uuid4())
            save_private(self.evidence_dir / (identifier + ".profile.json"), profile, self.settings)
            result = {"status": "confirmed", "merged_text": merged, "profile_id": identifier}
            session.profile_confirmed = profile
            session.profile_receipt = {"payload": copy.deepcopy(payload), "result": result}
            return result

    @staticmethod
    def validate_area(city, area):
        preset = PRESETS[city]
        delta = distance_m(Area(preset["lat"], preset["lon"]), {"lat": area.lat, "lon": area.lon})
        if delta is None or delta > 200000:
            raise ServiceError("AREA_CITY_MISMATCH", status=400)

    def compare(self, session, payload):
        if payload.get("draft_id") != session.draft_id or not session.confirmed:
            raise ServiceError("DRAFT_EXPIRED", status=409)
        values = copy.deepcopy(session.confirmed)
        values["interests"] = []
        intent = Intent.from_dict(values)
        session.qloo.max_calls = min(40, session.qloo.calls+14)
        before = session.qloo.calls
        result = DiscoveryEngine(session.qloo, session.verifier).run(intent, Area(**session.area),
            seen_ids=list(session.comparison_seen), independent_bookstore=session.independent_bookstore, allow_no_signals=True)
        # Same venue/radius/hard constraints/checks and seen-list snapshot; no profile mutation.
        return {key:value for key,value in result.items() if key in {"status","cards","source","error","questions","trace","diagnostics","taste_inputs","recommendation_mode"}} | {"qloo_network_attempts":session.qloo.calls-before}

    def discover(self, session, payload, identifier):
        if payload.get("draft_id") != session.draft_id or not session.intent:
            raise ServiceError("DRAFT_EXPIRED", status=409)
        if payload.get("again"):
            if not session.confirmed:
                raise ServiceError("CONFIRM_INTENT_FIRST", status=409)
            values = session.confirmed
        else:
            values = payload.get("intent")
        intent = Intent.from_dict(values)
        if any(secret and secret in interest.query for secret in [self.settings.qloo_key, self.settings.deepseek_key] for interest in intent.interests):
            raise ServiceError("SENSITIVE_INPUT_REJECTED", status=400)
        if intent.city != session.city:
            raise ServiceError("AREA_CITY_MISMATCH", status=400)
        area = Area(**session.area)
        if values != session.confirmed:
            session.shown, session.selections = set(), {}
        session.confirmed = asdict(intent)
        session.confirmed.pop("parser", None)
        selections = payload.get("selections", {})
        if not isinstance(selections, dict) or len(selections) > 8 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in selections.items()):
            raise ValueError("Invalid selections")
        session.selections.update(selections)
        def progress(state, details):
            with self.lock:
                session.jobs[identifier]["progress"] = state
        # A session caches private data, but each discovery still has a 14-attempt cap.
        session.qloo.max_calls = min(40, session.qloo.calls+14)
        before = session.qloo.calls
        session.comparison_seen = list(session.shown)
        result = DiscoveryEngine(session.qloo, session.verifier).run(intent, area,
                   seen_ids=list(session.shown), selections=session.selections, on_progress=progress, independent_bookstore=session.independent_bookstore)
        session.shown.update(card["entity_id"] for card in result["cards"])
        # No raw response or filesystem path is exposed through the browser API.
        return {key: value for key, value in result.items() if key in
                {"status", "source", "cards", "questions", "error", "trace", "run_id", "created_at", "diagnostics", "taste_inputs", "recommendation_mode"}} | {
                    "qloo_network_attempts": session.qloo.calls-before,
                    "filtered_count": len(result["rejections"]), "shown_count": len(session.shown)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CityPlayAI"
    def log_message(self, *args):
        pass  # Never log request bodies, personal queries or upstream errors.

    def respond(self, status, payload, content_type="application/json; charset=utf-8", cookie=None):
        if isinstance(payload, (dict, list)):
            raw = self.server.app.settings.redact(json.dumps(payload, ensure_ascii=False)).encode()
        else:
            raw = payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", "cityplay_session="+cookie+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800" + ("; Secure" if self.server.public_origin else ""))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def host_valid(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in self.server.allowed_hosts

    def browser_session(self, create=False):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            identifier = cookie["cityplay_session"].value if "cityplay_session" in cookie else None
        except Exception:
            identifier = None
        return self.server.app.session(identifier, create)

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == "/healthz":
            return self.respond(200, {"status": "ok"})
        if not self.host_valid():
            return self.respond(403, {"error": {"code": "UNTRUSTED_HOST"}})
        path = urllib.parse.urlsplit(self.path).path
        if path in STATIC:
            name, content_type = STATIC[path]
            return self.respond(200, (ROOT / "web" / name).read_bytes(), content_type)
        if path == "/api/session":
            identifier, session = self.browser_session(create=True)
            if not session:
                return self.respond(429, {"error": {"code": "SESSION_LIMIT"}})
            return self.respond(200, {"csrf": session.csrf, "presets": PRESETS,
                       "configured": {"qloo": bool(self.server.app.settings.qloo_key), "model": bool(self.server.app.settings.deepseek_key)}}, cookie=identifier)
        if path.startswith("/api/jobs/"):
            _, session = self.browser_session()
            with self.server.app.lock:
                job = session.jobs.get(path.removeprefix("/api/jobs/")) if session else None
                return self.respond(200, dict(job)) if job else self.respond(404, {"error": {"code": "JOB_NOT_FOUND"}})
        return self.respond(404, {"error": {"code": "NOT_FOUND"}})

    def do_POST(self):
        try:
            if not self.host_valid():
                raise ServiceError("UNTRUSTED_HOST", status=403)
            port = self.server.server_address[1]
            if self.headers.get("Origin") not in self.server.allowed_origins:
                raise ServiceError("UNTRUSTED_ORIGIN", status=403)
            _, session = self.browser_session()
            if not session or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), session.csrf):
                raise ServiceError("INVALID_SESSION_OR_CSRF", status=403)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ServiceError("JSON_REQUIRED", status=415)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16000:
                raise ServiceError("BODY_SIZE_LIMIT", status=413)
            self.connection.settimeout(5)
            def invalid_number(value):
                raise ValueError("Non-finite JSON number")
            body = json.loads(self.rfile.read(size), parse_constant=invalid_number)
            if not isinstance(body, dict):
                raise ValueError("Request must be an object")
            if self.path == "/api/profile/confirm":
                return self.respond(200, self.server.app.confirm_profile(session, body))
            if self.path == "/api/guess":
                if set(body) != {"answers"}: raise ValueError("Invalid questionnaire")
                kind = "guess"
            elif self.path == "/api/parse":
                if set(body) != {"query", "city", "area"}:
                    raise ValueError("Invalid parse request")
                kind = "parse"
            elif self.path == "/api/compare":
                if set(body) != {"draft_id"}: raise ValueError("Invalid comparison")
                kind = "compare"
            elif self.path == "/api/discover":
                if set(body) - {"draft_id", "intent", "again", "selections"}:
                    raise ValueError("Invalid discovery request")
                if "again" in body and type(body["again"]) is not bool:
                    raise ValueError("again must be boolean")
                kind = "discover"
            else:
                return self.respond(404, {"error": {"code": "NOT_FOUND"}})
            job = self.server.app.start(session, kind, body)
            self.respond(202, {"job_id": job})
        except ServiceError as error:
            self.respond(error.status or 400, {"error": {"code": error.code, "retryable": error.retryable}})
        except (ValueError, TypeError, OSError):
            self.respond(400, {"error": {"code": "INVALID_REQUEST"}})


def create_server(port=8787, app=None, *, host="127.0.0.1", public_origin=None):
    if host not in {"127.0.0.1", "localhost"} and not public_origin:
        raise ValueError("Public binding requires PUBLIC_ORIGIN")
    parsed = urllib.parse.urlsplit(public_origin or "")
    if public_origin and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("PUBLIC_ORIGIN must be a trusted HTTPS origin")
    server = ThreadingHTTPServer((host, port), Handler)
    server.public_origin = public_origin.rstrip("/") if public_origin else None
    bound_port = server.server_address[1]
    server.allowed_hosts = {parsed.netloc} if public_origin else {f"127.0.0.1:{bound_port}", f"localhost:{bound_port}"}
    server.allowed_origins = {server.public_origin} if public_origin else {f"http://127.0.0.1:{bound_port}", f"http://localhost:{bound_port}"}
    server.daemon_threads = True
    server.app = app or Application()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = create_server(args.port, Application(process_budget=int(os.environ.get("CITYPLAY_QLOO_HOURLY_BUDGET", "120"))), host=args.host, public_origin=os.environ.get("PUBLIC_ORIGIN"))
    print(f"CityPlay AI local preview: http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
