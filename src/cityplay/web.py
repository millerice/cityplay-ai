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
from .parallel import build_parallel, public_result
from .taste_cards import load_cards, selected_tastes
from .library import LibraryStore
from .models import MODEL_BY_ID, public_model_catalog

PRESETS = {
    "new_york": {"lat": 40.722668, "lon": -73.99823, "label": "纽约下城示例中心"},
    # 31°14′ N, 121°29′ E; public Shanghai Basic Facts, not private Qloo data.
    "shanghai": {"lat": 31 + 14/60, "lon": 121 + 29/60, "label": "上海示例中心 · 实验支持"},
}
STATIC = {"/library.js": ("library.js", "text/javascript; charset=utf-8"),"/map.js": ("map.js", "text/javascript; charset=utf-8"),"/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet.js": ("vendor/leaflet.js", "text/javascript; charset=utf-8"),
          "/vendor/leaflet.css": ("vendor/leaflet.css", "text/css; charset=utf-8"),"/guess.js": ("guess.js", "text/javascript; charset=utf-8"),"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


@dataclass
class Session:
    profile_id: str = ''
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    draft_id: str | None = None
    intent: dict | None = None
    city: str | None = None
    city_conflict: dict | None = None
    area: dict | None = None
    confirmed: dict | None = None
    shown: set = field(default_factory=set)
    comparison_seen: list = field(default_factory=list)
    selections: dict = field(default_factory=dict)
    busy: bool = False
    jobs: dict = field(default_factory=dict)
    submissions: list = field(default_factory=list)
    card_submissions: list = field(default_factory=list)
    qloo: object = None
    verifier: object = None
    independent_bookstore: bool = False
    profile_draft: dict | None = None
    profile_draft_id: str | None = None
    profile_confirmed: dict | None = None
    profile_receipt: dict | None = None
    last_cards: list = field(default_factory=list)
    feedback: dict = field(default_factory=dict)
    prefer_nearby: bool = False
    parallel_versions: list = field(default_factory=list)
    parallel_familiar: dict = field(default_factory=dict)
    taste_catalog: dict = field(default_factory=dict)
    taste_choices: list = field(default_factory=list)
    taste_curiosity: dict | None = None
    taste_starting_mode: str = 'likes'
    # Browser-supplied model credentials: in-memory only, never persisted.
    model_key: str = ""
    model_name: str = ""
    # Browser-supplied Qloo credential: in-memory only, never persisted.
    qloo_key: str = ""


class Application:
    def __init__(self, settings=None, *, model_factory=None, qloo_factory=None, verifier_factory=None,
                 evidence_dir=None, process_budget=120, budget_window_seconds=3600):
        self.settings = settings or Settings.load()
        self._builtin_model_factory = model_factory is None
        self.model_factory = model_factory or (lambda: DeepSeekClient(self.settings.deepseek_key, self.settings.model))
        self._builtin_qloo_factory = qloo_factory is None
        self.qloo_factory = qloo_factory or (lambda: QlooClient(self.settings.qloo_key, sender=self.qloo_network, max_calls=40))
        self.verifier_factory = verifier_factory or (lambda: WebsiteVerifier(max_checks=12))
        self.evidence_dir = evidence_dir or ROOT / ".qloo-private" / "stage3"
        self.library=LibraryStore(self.evidence_dir.parent/'cityplay.sqlite3')
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
            identifier = identifier if isinstance(identifier,str) and re.fullmatch(r'[A-Za-z0-9_-]{43}',identifier) and self.library.has_profile(identifier) else secrets.token_urlsafe(32)
            value = Session(profile_id=identifier,qloo=self.build_qloo(), verifier=self.verifier_factory())
            self.sessions[identifier] = value
            return identifier, value

    def secrets(self, session=None):
        # Keys that must never surface verbatim in user input, including any key
        # the browser supplied for this session.
        return tuple(key for key in (self.settings.qloo_key, self.settings.deepseek_key,
                                     getattr(session, "model_key", ""), getattr(session, "qloo_key", "")) if key)

    def update_credentials(self, session, model_key, model_name, qloo_key):
        # A browser tab supplies its own API credentials per request; they are
        # kept in the in-memory session only and an empty header clears them.
        model_key = model_key.strip() if isinstance(model_key, str) else ""
        model_name = model_name.strip() if isinstance(model_name, str) else ""
        if model_key and not re.fullmatch(r"[A-Za-z0-9_.\-]{8,200}", model_key):
            raise ServiceError("MODEL_KEY_INVALID", status=400)
        # Only curated presets are accepted; their base URLs stay server-side.
        if model_name and model_name not in MODEL_BY_ID:
            raise ServiceError("MODEL_KEY_INVALID", status=400)
        session.model_key, session.model_name = model_key, (model_name or session.model_name)
        qloo_key = qloo_key.strip() if isinstance(qloo_key, str) else ""
        if qloo_key and not re.fullmatch(r"[A-Za-z0-9_.\-]{8,200}", qloo_key):
            raise ServiceError("QLOO_KEY_INVALID", status=400)
        if qloo_key != session.qloo_key:
            session.qloo_key = qloo_key
            session.qloo = self.build_qloo(session)

    def build_model(self, session=None):
        # An explicitly injected factory (tests, local tools) always wins;
        # otherwise the browser-supplied key takes precedence over any built-in key.
        if not self._builtin_model_factory and self.model_factory:
            return self.model_factory()
        return DeepSeekClient(getattr(session, "model_key", "") or self.settings.deepseek_key,
                              getattr(session, "model_name", "") or self.settings.model)

    def build_qloo(self, session=None):
        # An injected factory (tests, local tools) wins; otherwise the
        # browser-supplied key takes precedence over any built-in key.
        if not self._builtin_qloo_factory and self.qloo_factory:
            return self.qloo_factory()
        return QlooClient(getattr(session, "qloo_key", "") or self.settings.qloo_key,
                          sender=self.qloo_network, max_calls=40)

    def start(self, session, kind, payload):
        with self.lock:
            now = time.monotonic()
            bucket=session.card_submissions if kind=='taste_cards' else session.submissions
            bucket[:]=[x for x in bucket if now-x < 60]
            if session.busy:
                raise ServiceError("JOB_ALREADY_RUNNING", status=409)
            if kind in {"parse", "guess"} and not (getattr(session, "model_key", "") or self.settings.deepseek_key):
                # No built-in key ships with the deployment; visitors bring their own.
                raise ServiceError("MODEL_KEY_REQUIRED", status=400, retryable=False)
            if kind in {"taste_cards", "discover", "parallel", "compare"} and not (getattr(session, "qloo_key", "") or self.settings.qloo_key):
                # Cultural search also runs on a visitor-supplied Qloo key.
                raise ServiceError("QLOO_KEY_REQUIRED", status=400, retryable=False)
            if len(bucket) >= (10 if kind=='taste_cards' else 6):
                raise ServiceError("LOCAL_REQUEST_LIMIT", status=429)
            if not self.slots.acquire(blocking=False):
                raise ServiceError("LOCAL_SERVICE_BUSY", retryable=True, status=429)
            session.busy = True
            bucket.append(now)
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
                answers = validate_answers(payload["answers"], self.secrets(session))
                model = self.build_model(session)
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
                if any(secret and secret in query for secret in self.secrets(session)) or re.search(r"\S+@\S+|\d{10,}", query):
                    raise ServiceError("SENSITIVE_INPUT_REJECTED", status=400)
                self.validate_area(city, area)
                model = self.build_model(session)
                city_context = "纽约附近" if city == "new_york" else "上海附近"
                intent = ModelIntentParser(model).parse(query + "\n页面上明确选择的探索区域：" + city_context)
                model_trace = model.trace
                if intent.city != city:
                    intent.clarifications.append("The requested city differs from the selected area; choose a matching area.")
                mentioned={name for name,pattern in [('new_york',r'纽约|\bnew york\b'),('shanghai',r'上海|\bshanghai\b')] if re.search(pattern,query,re.I)}
                requested=next(iter(mentioned)) if len(mentioned)==1 else None
                conflict={'selected':city,'requested':requested} if requested and requested!=city else None
                values = asdict(intent)
                values.pop("parser", None)
                with self.lock:
                    session.draft_id, session.intent = str(uuid.uuid4()), values
                    session.area, session.city = asdict(area), city
                    session.city_conflict=conflict
                    session.independent_bookstore = bool(re.search(r"independent book|indie book|独立书店", query, re.I))
                    session.confirmed, session.shown, session.selections = None, set(), {}
                    session.last_cards, session.prefer_nearby = [], False
                    session.parallel_versions, session.parallel_familiar = [], {}
                    session.taste_curiosity=None;session.taste_starting_mode='likes'
                result = {"status": "needs_confirmation", "draft_id": session.draft_id, "intent": values,
                          "city": city, "area": asdict(area), "model": model.model,"city_conflict":conflict}
            elif kind == "compare":
                result = self.compare(session, payload)
            elif kind == "parallel":
                result = self.parallel(session, payload)
            elif kind == 'taste_cards':
                result = load_cards(session,payload,self.secrets(session))
                self.library.put_entities(result['cards'])
            else:
                result = self.discover(session, payload, identifier)
            evidence = {"job_id": identifier, "kind": kind, "result": result, "model_tools": model_trace}
            if kind not in {"guess", "taste_cards"}:
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
            profile, merged = confirm(session.profile_draft, payload, self.secrets(session))
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
            seen_ids=list(session.comparison_seen), independent_bookstore=session.independent_bookstore, allow_no_signals=True, prefer_nearby=session.prefer_nearby)
        # Same venue/radius/hard constraints/checks and seen-list snapshot; no profile mutation.
        return {key:value for key,value in result.items() if key in {"status","cards","source","error","questions","trace","diagnostics","taste_inputs","recommendation_mode"}} | {"qloo_network_attempts":session.qloo.calls-before}

    def prepare_taste(self, session, payload):
        city=payload['city'];area=Area(**payload['area'])
        if city not in PRESETS: raise ValueError('Unsupported city')
        self.validate_area(city,area)
        intent=Intent.from_dict({'city':city,'interests':payload['interests'],'categories':payload['categories'],'exclude_categories':payload.get('exclude_categories',[])})
        if not intent.interests: raise ValueError('Choose at least one taste')
        for interest in intent.interests:
            if any(key and key in interest.query for key in self.secrets(session)):
                raise ServiceError('SENSITIVE_INPUT_REJECTED',status=400)
        values=asdict(intent);values.pop('parser')
        with self.lock:
            if session.busy: raise ServiceError('JOB_ALREADY_RUNNING',status=409)
            session.draft_id=str(uuid.uuid4());session.intent=values
            session.area=asdict(area);session.city=city;session.confirmed=None;session.city_conflict=None
            session.shown=set();session.selections={};session.last_cards=[]
            session.parallel_versions=[];session.parallel_familiar={};session.prefer_nearby=False;session.independent_bookstore=False
            session.taste_curiosity=None;session.taste_starting_mode='likes'
        return {'status':'needs_confirmation','draft_id':session.draft_id,'intent':values,'area':session.area,'city':city,'model':'structured taste input'}

    def browse_library(self,session,payload):
        if set(payload)-{'domain','query','offset'}:raise ValueError('Invalid browse')
        query=payload.get('query','')
        if not isinstance(query,str):raise ValueError('Invalid query')
        if any(secret and secret in query for secret in self.secrets(session)):raise ServiceError('SENSITIVE_INPUT_REJECTED',status=400)
        result=self.library.browse(payload.get('domain','all'),query,payload.get('offset',0),discovery_only=not query.strip())
        for card in result['cards']:session.taste_catalog[card['id']]=card
        choices=self.library.choices(session.profile_id)
        for item in choices:session.taste_catalog[item['id']]=item
        result['choices']=choices
        return result

    def library_choice(self,session,payload):
        if set(payload)!={'id','choice'} or not isinstance(payload['id'],str):raise ValueError('Invalid choice')
        card=session.taste_catalog.get(payload['id']) or self.library.card_by_id(payload['id'])
        if not card:raise ValueError('Unknown card')
        return {'choices':self.library.choose(session.profile_id,card,payload['choice'])}

    def apply_taste_cards(self,session,payload):
        with self.lock:
            if session.busy: raise ServiceError('JOB_ALREADY_RUNNING',status=409)
            likes,curious=selected_tastes(session,payload['items'])
            prior=None
            prior_conflict=copy.deepcopy(session.city_conflict) if payload.get('draft_id') else None
            prior_independent=session.independent_bookstore
            if payload.get('draft_id'):
                if payload['draft_id']!=session.draft_id or not session.intent: raise ServiceError('DRAFT_EXPIRED',status=409)
                prior=copy.deepcopy(session.intent)
                if payload['city']!=session.city or payload['area']!=session.area: raise ValueError('Area changed')
            anchors=likes or curious
            values={key:payload[key] for key in ('city','area','categories')}
            if 'exclude_categories' in payload:values['exclude_categories']=payload['exclude_categories']
            values['interests']=[{'kind':'entity','query':x['name'],'entity_type':x['entity_type']} for x in anchors]
            draft=self.prepare_taste(session,values)
            if prior:
                for key in ('exclude_categories','max_budget','available_minutes','open_now','strict_city','novelty_requested','clarifications'):
                    if key=='exclude_categories' and key in payload:continue
                    draft['intent'][key]=prior[key]
                session.intent=copy.deepcopy(draft['intent'])
                session.independent_bookstore=prior_independent
                session.city_conflict=prior_conflict
                draft['city_conflict']=prior_conflict
            session.taste_choices=copy.deepcopy(payload['items'])
            self.library.merge_choices(session.profile_id,[(x,'like') for x in likes]+[(x,'curious') for x in curious])
            session.taste_curiosity=curious[0] if curious and likes else None
            draft['selections']={f'interests.{i}':x['id'] for i,x in enumerate(anchors)}
            draft['curiosity']=session.taste_curiosity
            draft['active_tastes']=[{**x,'choice':'like'} for x in likes]+[{**x,'choice':'curious'} for x in curious]
            draft['starting_mode']='curiosity' if not likes else 'likes'
            session.taste_starting_mode=draft['starting_mode']
            return draft

    def parallel(self, session, payload):
        if payload.get('draft_id') != session.draft_id or not session.confirmed or not session.parallel_familiar.get('cards'):
            raise ServiceError('DRAFT_EXPIRED', status=409)
        original=copy.deepcopy(session.parallel_versions[0]["intent"] if session.parallel_versions else session.confirmed)
        alternative=payload.get('alternative')
        if alternative is None and session.taste_curiosity:
            c=session.taste_curiosity
            alternative={'kind':'entity','query':c['name'],'entity_type':c['entity_type']}
        if alternative is not None:
            candidate={**original,'interests':[alternative]}
            Intent.from_dict(candidate)
            if any(key and key in alternative['query'] for key in self.secrets(session)):
                raise ServiceError('SENSITIVE_INPUT_REJECTED',status=400)
        context={'kind':'parallel','intent':original,'area':session.area,'alternative':alternative,'feedback':session.feedback,
                 'independent':session.independent_bookstore,'nearby':session.prefer_nearby}
        cached=self.library.get_snapshot(session.profile_id,context)
        if cached:
            session.parallel_versions=cached['versions']
            for version in session.parallel_versions:
                version['result'].update(source='cached_qloo',cache_origin='sqlite',cached_at=cached['cached_at'])
            return {'status':'parallel','versions':session.parallel_versions}
        session.qloo.max_calls=min(40,session.qloo.calls+14)
        session.parallel_versions=build_parallel(session)
        if alternative:
            values={**original,'interests':[alternative]}
            result=DiscoveryEngine(session.qloo,session.verifier).run(Intent.from_dict(values),Area(**session.area),
                seen_ids=list(session.feedback),independent_bookstore=session.independent_bookstore,prefer_nearby=session.prefer_nearby,
                selections={'interests.0':session.taste_curiosity['id']} if session.taste_curiosity and alternative['query']==session.taste_curiosity['name'] else {})
            session.parallel_versions.append({'id':'alternative','variant':'alternative','title':'Alternative me','subtitle':'A new starting point you chose',
                'intent':values,'result':result,'path':[],'boundary':'An exploration direction you picked — not a hidden personality the system discovered.'})
        result={'status':'parallel','versions':[{**v,'result':public_result(v['result'])} for v in session.parallel_versions]}
        if all(v['result'].get('status') in {'partial','empty'} for v in session.parallel_versions):self.library.put_snapshot(session.profile_id,context,result)
        return result

    def select_parallel(self, session, payload):
        with self.lock:
            if session.busy: raise ServiceError('JOB_ALREADY_RUNNING',status=409)
            if payload.get('draft_id') != session.draft_id: raise ServiceError('DRAFT_EXPIRED',status=409)
            version=next((x for x in session.parallel_versions if x['id']==payload.get('version')),None)
            if not version: raise ValueError('Unknown parallel version')
            session.confirmed=copy.deepcopy(version['intent'])
            session.selections={}
            result=copy.deepcopy(version['result'])
            result['cards']=[x for x in result.get('cards',[]) if x['entity_id'] not in session.feedback]
            if result.get('status')=='partial' and not result['cards']: result['status']='empty'
            session.last_cards=result['cards']
            session.shown=set(session.feedback)|{x['entity_id'] for x in result['cards']}
            session.comparison_seen=list(session.feedback)
            return {'version':version['id'],'intent':session.confirmed,'result':public_result(result)}

    def discover(self, session, payload, identifier):
        if session.city_conflict:raise ServiceError('CITY_SELECTION_REQUIRED',status=409)
        if payload.get("draft_id") != session.draft_id or not session.intent:
            raise ServiceError("DRAFT_EXPIRED", status=409)
        if payload.get("again"):
            if not session.confirmed:
                raise ServiceError("CONFIRM_INTENT_FIRST", status=409)
            values = session.confirmed
        else:
            values = payload.get("intent")
        intent = Intent.from_dict(values)
        feedback = payload.get('feedback')
        if feedback is not None:
            if not isinstance(feedback, dict) or set(feedback) != {'entity_id','reason'} or feedback.get('reason') not in {'not_now','experienced_dislike','too_far'} or feedback.get('entity_id') not in {x['entity_id'] for x in session.last_cards}:
                raise ValueError('Invalid feedback')
        if any(secret and secret in interest.query for secret in self.secrets(session) for interest in intent.interests):
            raise ServiceError("SENSITIVE_INPUT_REJECTED", status=400)
        if intent.city != session.city:
            raise ServiceError("AREA_CITY_MISMATCH", status=400)
        area = Area(**session.area)
        if values != session.confirmed:
            session.shown, session.selections = set(), {}
        session.confirmed = asdict(intent)
        session.confirmed.pop("parser", None)
        if feedback:
            session.feedback[feedback['entity_id']] = feedback['reason']
            if feedback['reason'] == 'too_far': session.prefer_nearby = True
            # Reconsider other cards, exclude the rejected venue without inventing a taste change.
            session.shown = set(session.feedback)
        session.shown.update(session.feedback)
        selections = payload.get("selections", {})
        if not isinstance(selections, dict) or len(selections) > 8 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in selections.items()):
            raise ValueError("Invalid selections")
        if any(secret and secret in part for secret in self.secrets(session) for k,v in selections.items() for part in (k,v)):
            raise ServiceError('SENSITIVE_INPUT_REJECTED',status=400)
        session.selections.update(selections)
        def progress(state, details):
            with self.lock:
                session.jobs[identifier]["progress"] = state
        # A session caches private data, but each discovery still has a 14-attempt cap.
        session.qloo.max_calls = min(40, session.qloo.calls+14)
        before = session.qloo.calls
        session.comparison_seen = list(session.shown)
        context={'intent':session.confirmed,'area':session.area,'seen':sorted(session.shown),'selections':session.selections,
                 'independent':session.independent_bookstore,'nearby':session.prefer_nearby}
        result=self.library.get_snapshot(session.profile_id,context)
        if result is None:
            result = DiscoveryEngine(session.qloo, session.verifier).run(intent, area,
                       seen_ids=list(session.shown), selections=session.selections, on_progress=progress, independent_bookstore=session.independent_bookstore, prefer_nearby=session.prefer_nearby)
            self.library.put_snapshot(session.profile_id,context,result)
        session.last_cards = result['cards']
        if not session.parallel_versions: session.parallel_familiar=copy.deepcopy(result)
        else:
            for version in session.parallel_versions:
                if version['intent']==session.confirmed: version['result']=copy.deepcopy(result)
        session.shown.update(card["entity_id"] for card in result["cards"])
        # No raw response or filesystem path is exposed through the browser API.
        return {key: value for key, value in result.items() if key in
                {"status", "source", "cards", "questions", "error", "trace", "run_id", "created_at", "diagnostics", "taste_inputs", "recommendation_mode", "cache_origin", "cached_at"}} | {
                    "qloo_network_attempts": session.qloo.calls-before,
                    "filtered_count": len(result["rejections"]), "shown_count": len(session.shown),
                    "feedback_count": len(session.feedback), "prefer_nearby": session.prefer_nearby}


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
            self.send_header("Set-Cookie", "cityplay_session="+cookie+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000" + ("; Secure" if self.server.public_origin else ""))
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
            return self.respond(200, {"csrf": session.csrf, "presets": PRESETS, "models": public_model_catalog(),
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
            self.server.app.update_credentials(session, self.headers.get("X-Model-Key", ""), self.headers.get("X-Model-Name", ""), self.headers.get("X-Qloo-Key", ""))
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
            if self.path == '/api/taste/prepare':
                if set(body) != {'city','area','interests','categories'}: raise ValueError('Invalid taste input')
                return self.respond(200,self.server.app.prepare_taste(session,body))
            if self.path == '/api/taste/cards/confirm':
                if set(body)-{'city','area','categories','items','draft_id','exclude_categories'} or not {'city','area','categories','items'}<=set(body): raise ValueError('Invalid card confirmation')
                return self.respond(200,self.server.app.apply_taste_cards(session,body))
            if self.path == '/api/library/browse':
                return self.respond(200,self.server.app.browse_library(session,body))
            if self.path == '/api/library/choice':
                return self.respond(200,self.server.app.library_choice(session,body))
            if self.path == '/api/library/clear':
                if body:raise ValueError('Invalid reset')
                self.server.app.library.clear(session.profile_id)
                return self.respond(200,{'choices':[]})
            if self.path == '/api/parallel/select':
                if set(body) != {'draft_id','version'}: raise ValueError('Invalid version selection')
                return self.respond(200,self.server.app.select_parallel(session,body))
            if self.path == "/api/guess":
                if set(body) != {"answers"}: raise ValueError("Invalid questionnaire")
                kind = "guess"
            elif self.path == '/api/taste/cards':
                kind='taste_cards'
            elif self.path == "/api/parse":
                if set(body) != {"query", "city", "area"}:
                    raise ValueError("Invalid parse request")
                kind = "parse"
            elif self.path == "/api/compare":
                if set(body) != {"draft_id"}: raise ValueError("Invalid comparison")
                kind = "compare"
            elif self.path == '/api/parallel':
                if set(body)-{'draft_id','alternative'}: raise ValueError('Invalid parallel request')
                kind='parallel'
            elif self.path == "/api/discover":
                if set(body) - {"draft_id", "intent", "again", "selections", "feedback"}:
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
    # Hosting platforms assign the public HTTPS origin at deploy time;
    # RENDER_EXTERNAL_URL is Render's injected equivalent of PUBLIC_ORIGIN.
    public_origin = os.environ.get("PUBLIC_ORIGIN") or os.environ.get("RENDER_EXTERNAL_URL")
    server = create_server(args.port, Application(process_budget=int(os.environ.get("CITYPLAY_QLOO_HOURLY_BUDGET", "120"))), host=args.host, public_origin=public_origin)
    print(f"CityPlay AI local preview: http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
