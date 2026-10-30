"""Local HTTP integration checks with synthetic model and Qloo transports."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from cityplay.config import Settings
from cityplay.transport import QlooClient, Response
from cityplay.verify import WebsiteVerifier
from cityplay.web import Application, create_server


class Model:
    model = "synthetic-model"
    trace = []
    def parse_json(self, system, query):
        return {"city": "new_york", "interests": [{"kind": "entity", "query": "SYNTHETIC ARTIST", "entity_type": "artist"}],
                "categories": ["bookstore"], "exclude_categories": [], "clarifications": [], "open_now": False,
                "strict_city": False, "novelty_requested": False, "available_minutes": None, "max_budget": None}


def synthetic_sender(method, url, headers, *args, **kwargs):
    if "/search?" in url:
        return Response(200, {}, {"results": [{"entity_id": "synthetic-artist", "name": "SYNTHETIC ARTIST", "types": ["urn:entity:artist"]}]})
    if "/v2/tags?" in url:
        return Response(200, {}, {"results": {"tags": [{"id": "urn:tag:setting:synthetic:books", "name": "Independent Bookstore", "type": "urn:tag:setting:qloo"}, {"id": "urn:tag:category:synthetic:books", "name": "Book store", "type": "urn:tag:category:place"}]}})
    return Response(200, {}, {"success": True, "results": {"entities": [
        {"entity_id": "synthetic-"+str(index), "name": "Synthetic Bookshop "+str(index), "subtype": "urn:entity:place",
         "location": {"lat": 40.722668, "lon": -73.99823}, "query": {"affinity": .5},
         "properties": {"address": "SYNTHETIC ADDRESS", "primary_genre": {"name": "Book store"}, "website": "https://synthetic.invalid/"}}
        for index in range(4)]}})


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Settings("synthetic-qloo-key", "synthetic-model-key"), model_factory=Model,
            qloo_factory=lambda: QlooClient("synthetic-qloo-key", sender=synthetic_sender, sleep=lambda seconds: None),
            verifier_factory=lambda: WebsiteVerifier(fetch=lambda url: (url, "Synthetic Bookshop 0 Synthetic Bookshop 1 Synthetic Bookshop 2 Synthetic Bookshop 3")),
            evidence_dir=Path(self.temp.name)/"evidence")
        self.server = create_server(0, self.app)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.cookie, self.csrf = self.new_session()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.temp.cleanup()

    def request(self, method, path, body=None, cookie=None, csrf=None, origin=None, extra=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json", "Origin": origin or f"http://127.0.0.1:{self.port}"}
        if cookie: headers["Cookie"] = cookie
        if csrf: headers["X-CSRF-Token"] = csrf
        if extra: headers.update(extra)
        raw = json.dumps(body) if isinstance(body, (dict, list)) else body
        connection.request(method, path, body=raw, headers=headers)
        response = connection.getresponse(); status, response_headers = response.status, dict(response.getheaders()); raw = response.read()
        connection.close()
        return status, response_headers, raw

    def new_session(self):
        status, headers, raw = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0], json.loads(raw)["csrf"]

    def post(self, path, body):
        return self.request("POST", path, body, self.cookie, self.csrf)

    def wait(self, identifier):
        for _ in range(100):
            status, _, raw = self.request("GET", "/api/jobs/"+identifier, cookie=self.cookie)
            self.assertEqual(status, 200); job = json.loads(raw)
            if job["status"] != "running":return job
            time.sleep(.01)
        self.fail("Synthetic job did not finish")

    def parse(self):
        status, _, raw = self.post("/api/parse", {"query": "public synthetic artist and books", "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823, "radius_m": 10000}})
        self.assertEqual(status, 202)
        return self.wait(json.loads(raw)["job_id"])["result"]

    def test_static_allowlist_and_security_headers(self):
        status, headers, raw = self.request("GET", "/")
        self.assertEqual(status, 200); self.assertIn(b"CityPlay", raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("https://tile.openstreetmap.org", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        for asset in ["/map.js", "/vendor/leaflet.js", "/vendor/leaflet.css"]:
            self.assertEqual(self.request("GET", asset)[0], 200)
        for path in ["/.env.local", "/.qloo-private/", "/src/cityplay/config.py", "/../.env.local", "/%2e%2e/.env.local"]:
            status, _, raw = self.request("GET", path)
            self.assertEqual(status, 404)
            self.assertNotIn(b"synthetic-qloo-key", raw)

    def test_cross_origin_csrf_and_host_rejected(self):
        body = {"query": "hello", "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823}}
        self.assertEqual(self.request("POST", "/api/parse", body, self.cookie, self.csrf, origin="https://untrusted.invalid")[0], 403)
        self.assertEqual(self.request("POST", "/api/parse", body, self.cookie, "wrong-csrf")[0], 403)
        self.assertEqual(self.request("GET", "/", extra={"Host": "untrusted.invalid"})[0], 403)

    def test_job_cannot_be_read_from_another_browser_session(self):
        status, _, raw = self.post("/api/parse", {"query": "public interest", "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823}})
        identifier = json.loads(raw)["job_id"]
        other_cookie, _ = self.new_session()
        self.assertEqual(self.request("GET", "/api/jobs/"+identifier, cookie=other_cookie)[0], 404)
        self.wait(identifier)

    def test_confirmation_and_again_use_real_gates_and_cache(self):
        draft = self.parse()
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "intent": draft["intent"]})
        result = self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(result["status"], "partial"); self.assertEqual(len(result["cards"]), 3)
        self.assertEqual(result["qloo_network_attempts"], 3)
        first = {x["entity_id"] for x in result["cards"]}
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "again": True})
        result = self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(len(result["cards"]), 1); self.assertEqual(result["qloo_network_attempts"], 0)
        self.assertFalse(first & {x["entity_id"] for x in result["cards"]})
        self.assertEqual(result["source"], "cached_qloo")
        self.assertNotIn("evidence_file", result)

    def test_explicit_budget_stays_blocked_after_confirmation(self):
        draft = self.parse(); draft["intent"]["max_budget"] = {"amount": 50, "currency": "USD"}
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "intent": draft["intent"]})
        result = self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(result["status"], "empty"); self.assertEqual(result["cards"], [])

    def test_upstream_auth_failure_reaches_browser_as_error_not_empty_or_fake_cards(self):
        draft = self.parse()
        current = self.app.sessions[self.cookie.split("=", 1)[1]].qloo
        current._sender = lambda *args, **kwargs: Response(401, {}, {})
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "intent": draft["intent"]})
        result = self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "QLOO_AUTH")
        self.assertEqual(result["cards"], [])
        self.assertNotIn("synthetic-qloo-key", json.dumps(result))

    def test_model_never_receives_known_secrets_or_contact_identifiers(self):
        for query in ["synthetic-qloo-key", "person@example.com", "12345678901"]:
            status, _, raw = self.post("/api/parse", {"query": query, "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823}})
            job = self.wait(json.loads(raw)["job_id"])
            self.assertEqual(job["status"], "failed"); self.assertEqual(job["error"]["code"], "SENSITIVE_INPUT_REJECTED")

    def test_model_key_is_brought_by_the_browser_not_the_server(self):
        self.app.settings = Settings("synthetic-qloo-key", "")  # Deployments ship without a built-in key.
        payload = {"query": "public synthetic artist and books", "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823, "radius_m": 10000}}
        status, _, raw = self.post("/api/parse", payload)
        self.assertEqual(status, 400); self.assertEqual(json.loads(raw)["error"]["code"], "MODEL_KEY_REQUIRED")
        status, _, raw = self.request("POST", "/api/parse", payload, self.cookie, self.csrf, extra={"X-Model-Key": "bad key!"})
        self.assertEqual(status, 400); self.assertEqual(json.loads(raw)["error"]["code"], "MODEL_KEY_INVALID")
        status, _, raw = self.request("POST", "/api/parse", payload, self.cookie, self.csrf,
                                      extra={"X-Model-Key": "sk-browser-synthetic-key", "X-Model-Name": "bad name!"})
        self.assertEqual(status, 400); self.assertEqual(json.loads(raw)["error"]["code"], "MODEL_KEY_INVALID")
        status, _, raw = self.request("POST", "/api/parse", payload, self.cookie, self.csrf,
                                      extra={"X-Model-Key": "sk-browser-synthetic-key", "X-Model-Name": "deepseek-v4-flash"})
        self.assertEqual(status, 202)
        result = self.wait(json.loads(raw)["job_id"])["result"]
        self.assertTrue(result["intent"]["interests"])
        # Any well-formed model id is accepted, not only the presets.
        status, _, raw = self.request("POST", "/api/parse", payload, self.cookie, self.csrf,
                                      extra={"X-Model-Key": "sk-browser-synthetic-key", "X-Model-Name": "deepseek-reasoner"})
        self.assertEqual(status, 202)
        self.wait(json.loads(raw)["job_id"])
        # The browser-supplied key is itself a secret and must not reach the model.
        status, _, raw = self.request("POST", "/api/parse", {**payload, "query": "places like sk-browser-synthetic-key"},
                                      self.cookie, self.csrf, extra={"X-Model-Key": "sk-browser-synthetic-key"})
        job = self.wait(json.loads(raw)["job_id"])
        self.assertEqual(job["status"], "failed"); self.assertEqual(job["error"]["code"], "SENSITIVE_INPUT_REJECTED")
        # Clearing the header clears the session key again.
        status, _, raw = self.post("/api/parse", payload)
        self.assertEqual(status, 400); self.assertEqual(json.loads(raw)["error"]["code"], "MODEL_KEY_REQUIRED")

    def test_model_validation_details_reach_browser_without_raw_output(self):
        class InvalidModel:
            model = "synthetic"
            calls = 0
            trace = []
            def parse_json(self, system, query):
                self.calls += 1
                return {"interests": [{"kind": "tag", "query": ""}]}
        model = InvalidModel()
        self.app.model_factory = lambda: model
        status, _, raw = self.post("/api/parse", {"query": "public synthetic interest", "city": "new_york", "area": {"lat": 40.722668, "lon": -73.99823}})
        job = self.wait(json.loads(raw)["job_id"])
        self.assertEqual(model.calls, 2)
        self.assertEqual(job["error"]["code"], "INVALID_MODEL_INTENT")
        self.assertEqual(job["error"]["details"]["field"], "interests[0].query")
        error_files = list((Path(self.temp.name)/"evidence").glob("*.error.json"))
        self.assertEqual(len(error_files), 1)
        self.assertNotIn("public synthetic interest", error_files[0].read_text())

    def test_feedback_rejects_forged_place_and_preserves_taste(self):
        draft=self.parse()
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'intent':draft['intent']})
        first=self.wait(json.loads(raw)['job_id'])['result']
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        original=json.dumps(session.confirmed,sort_keys=True)
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'again':True,'feedback':{'entity_id':'forged','reason':'too_far'}})
        self.assertEqual(self.wait(json.loads(raw)['job_id'])['status'],'failed')
        self.assertEqual(session.feedback,{})
        rejected=first['cards'][0]['entity_id']
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'again':True,'feedback':{'entity_id':rejected,'reason':'too_far'}})
        result=self.wait(json.loads(raw)['job_id'])['result']
        self.assertTrue(result['prefer_nearby'])
        self.assertNotIn(rejected,[c['entity_id'] for c in result['cards']])
        self.assertEqual(json.dumps(session.confirmed,sort_keys=True),original)

    def test_local_library_browse_and_choices_need_no_qloo_and_survive_memory_restart(self):
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        self.app.library.put_entities([{'id':'local-card','name':'Local Synthetic Artist','entity_type':'artist'}],discovery=True)
        before=session.qloo.calls
        status,_,raw=self.post('/api/library/browse',{'domain':'music'})
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['cards'][0]['id'],'local-card')
        self.assertEqual(session.qloo.calls,before)
        status,_,raw=self.post('/api/library/choice',{'id':'local-card','choice':'curious'})
        self.assertEqual(status,200)
        self.app.sessions.clear()
        status,headers,raw=self.request('GET','/api/session',cookie=self.cookie)
        self.assertEqual(status,200)
        newcsrf=json.loads(raw)['csrf']
        status,_,raw=self.request('POST','/api/library/browse',{'domain':'music'},cookie=self.cookie,csrf=newcsrf)
        self.assertEqual(json.loads(raw)['choices'][0]['choice'],'curious')
        self.assertEqual(status,200)

    def test_explicit_city_conflict_is_structured_for_actionable_choice(self):
        payload={'query':'我喜欢 Miles Davis，想在纽约喝咖啡','city':'shanghai',
                 'area':{'lat':31.233333333333334,'lon':121.48333333333333,'radius_m':10000}}
        status,_,raw=self.post('/api/parse',payload)
        self.assertEqual(status,202)
        result=self.wait(json.loads(raw)['job_id'])['result']
        self.assertEqual(result['city_conflict'],{'requested':'new_york','selected':'shanghai'})
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        session.taste_catalog['known']={'id':'known','name':'Synthetic Artist','entity_type':'artist'}
        applied=self.app.apply_taste_cards(session,{'city':'shanghai','area':payload['area'],'categories':[],
            'draft_id':result['draft_id'],'items':[{'id':'known','choice':'like'}]})
        self.assertEqual(applied['city_conflict'],result['city_conflict'])
        from cityplay.transport import ServiceError
        with self.assertRaises(ServiceError) as failure:
            self.app.discover(session,{'draft_id':applied['draft_id'],'intent':applied['intent']},'synthetic')
        self.assertEqual(failure.exception.code,'CITY_SELECTION_REQUIRED')

    def test_online_cultural_search_issues_selectable_ids_and_caches_actual_names(self):
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        before=session.qloo.calls
        status,_,raw=self.post('/api/taste/cards',{'domain':'music','query':'synthetic alias','page':0})
        self.assertEqual(status,202)
        result=self.wait(json.loads(raw)['job_id'])['result']
        self.assertEqual(result['cards'][0]['name'],'SYNTHETIC ARTIST')
        self.assertGreater(session.qloo.calls,before)
        local=self.app.library.browse(query='SYNTHETIC ARTIST')
        self.assertEqual(local['cards'][0]['id'],result['cards'][0]['id'])
        status,_,raw=self.post('/api/library/choice',{'id':result['cards'][0]['id'],'choice':'like'})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['choices'][0]['id'],result['cards'][0]['id'])

    def test_discovery_snapshot_is_reused_for_identical_new_draft(self):
        draft=self.parse()
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'intent':draft['intent']})
        first=self.wait(json.loads(raw)['job_id'])['result']
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        calls=session.qloo.calls
        draft=self.parse()
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'intent':draft['intent']})
        second=self.wait(json.loads(raw)['job_id'])['result']
        self.assertEqual(second['cache_origin'],'sqlite')
        self.assertEqual(session.qloo.calls,calls)
        self.assertEqual(second['cards'],first['cards'])

    def test_parallel_bundle_reuses_local_snapshot_without_new_qloo(self):
        draft=self.parse()
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'intent':draft['intent']})
        self.wait(json.loads(raw)['job_id'])
        _,_,raw=self.post('/api/parallel',{'draft_id':draft['draft_id']})
        self.wait(json.loads(raw)['job_id'])
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        count=session.qloo.calls
        _,_,raw=self.post('/api/parallel',{'draft_id':draft['draft_id']})
        result=self.wait(json.loads(raw)['job_id'])['result']
        self.assertEqual(session.qloo.calls,count)
        self.assertEqual(result['versions'][0]['result']['cache_origin'],'sqlite')

    def test_card_confirmation_accepts_only_issued_entities_and_keeps_constraints(self):
        draft=self.parse()
        session=self.app.sessions[self.cookie.split('=',1)[1]]
        session.intent['max_budget']={'amount':20,'currency':'USD'}
        session.independent_bookstore=True
        _,_,raw=self.post('/api/taste/cards',{'domain':'music','query':'SYNTHETIC ARTIST'})
        cards=self.wait(json.loads(raw)['job_id'])['result']['cards']
        self.assertEqual(cards[0]['id'],'synthetic-artist')
        payload={'city':'new_york','area':session.area,'categories':['bookstore'],'draft_id':draft['draft_id'],'items':[{'id':'forged','choice':'like'}]}
        self.assertEqual(self.post('/api/taste/cards/confirm',payload)[0],400)
        payload['items']=[{'id':cards[0]['id'],'choice':'curious'}]
        status,_,raw=self.post('/api/taste/cards/confirm',payload)
        self.assertEqual(status,200)
        result=json.loads(raw)
        self.assertEqual(result['starting_mode'],'curiosity')
        self.assertEqual(result['intent']['max_budget'],{'amount':20,'currency':'USD'})
        self.assertTrue(session.independent_bookstore)
        self.assertEqual(session.taste_choices[0]['choice'],'curious')
        self.assertEqual(result['selections'],{'interests.0':'synthetic-artist'})

    def test_exploration_subset_does_not_overwrite_saved_library(self):
        self.parse();session=next(iter(self.app.sessions.values()))
        for index in range(8):
            card={'id':'saved-'+str(index),'name':'SYNTHETIC '+str(index),'entity_type':'artist'}
            session.taste_catalog[card['id']]=card
            choice='like' if index<5 else 'curious'
            status,_,_=self.post('/api/library/choice',{'id':card['id'],'choice':choice})
            self.assertEqual(status,200)
        saved=self.app.library.choices(session.profile_id)
        payload={'city':'new_york','area':session.area,'categories':[],
                 'items':[{'id':'saved-4','choice':'like'},{'id':'saved-7','choice':'curious'}]}
        status,_,raw=self.post('/api/taste/cards/confirm',payload)
        self.assertEqual(status,200);draft=json.loads(raw)
        self.assertEqual(len(draft['intent']['interests']),1)
        self.assertEqual(draft['curiosity']['id'],'saved-7')
        self.assertEqual(self.app.library.choices(session.profile_id),saved)
        payload['items']=[{'id':'saved-'+str(i),'choice':'like'} for i in range(5)]
        self.assertEqual(self.post('/api/taste/cards/confirm',payload)[0],400)
        self.assertEqual(self.app.library.choices(session.profile_id),saved)

    def test_direct_taste_prepare_validates_without_model_and_keeps_area(self):
        payload={'city':'new_york','area':{'lat':40.722668,'lon':-73.99823,'radius_m':10000},'interests':[{'kind':'entity','query':'SYNTHETIC ARTIST','entity_type':'artist'}],'categories':['bookstore']}
        status,_,raw=self.post('/api/taste/prepare',payload)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['intent']['interests'],payload['interests'])
        self.assertEqual(json.loads(raw)['intent']['exclude_categories'],[])
        payload['exclude_categories']=['hotel']
        session=next(iter(self.app.sessions.values()))
        draft=self.app.prepare_taste(session,payload)
        self.assertEqual(draft['intent']['exclude_categories'],['hotel'])
        payload['interests']=[]
        self.assertEqual(self.post('/api/taste/prepare',payload)[0],400)
        payload['interests']=[{'kind':'entity','query':'synthetic-qloo-key','entity_type':'artist'}]
        self.assertEqual(self.post('/api/taste/prepare',payload)[0],400)

    def test_parallel_jobs_and_selection_are_bound_to_current_draft(self):
        draft=self.parse()
        _,_,raw=self.post('/api/discover',{'draft_id':draft['draft_id'],'intent':draft['intent']})
        self.wait(json.loads(raw)['job_id'])
        _,_,raw=self.post('/api/parallel',{'draft_id':draft['draft_id']})
        result=self.wait(json.loads(raw)['job_id'])['result']
        self.assertEqual(result['status'],'parallel')
        self.assertEqual(result['versions'][0]['id'],'familiar')
        self.assertEqual(len(result['versions'][0]['result']['cards']),3)
        status,_,raw=self.post('/api/parallel/select',{'draft_id':draft['draft_id'],'version':'familiar'})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['intent'],draft['intent'])
        status,_,raw=self.post('/api/parallel/select',{'draft_id':draft['draft_id'],'version':'invented'})
        self.assertEqual(status,400)

    def test_comparison_preserves_session_state_and_same_constraints(self):
        draft=self.parse()
        _,_,raw=self.post("/api/discover",{"draft_id":draft["draft_id"],"intent":draft["intent"]})
        self.wait(json.loads(raw)["job_id"])
        session=self.app.sessions[self.cookie.split("=",1)[1]]
        original=json.dumps(session.confirmed,sort_keys=True);shown=set(session.shown)
        _,_,raw=self.post("/api/compare",{"draft_id":draft["draft_id"]})
        result=self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(result["recommendation_mode"],"category_baseline")
        self.assertEqual(len(result["cards"]),3)
        self.assertEqual(json.dumps(session.confirmed,sort_keys=True),original)
        self.assertEqual(session.shown,shown)
        self.assertEqual(session.comparison_seen,[])
        query=session.qloo.trace[-1]["query"]
        self.assertIn("filter.tags",query)
        self.assertNotIn("signal.interests.entities",query)

    def test_comparison_reuses_latest_discovery_seen_snapshot(self):
        draft=self.parse()
        _,_,raw=self.post("/api/discover",{"draft_id":draft["draft_id"],"intent":draft["intent"]})
        self.wait(json.loads(raw)["job_id"])
        _,_,raw=self.post("/api/discover",{"draft_id":draft["draft_id"],"again":True})
        self.wait(json.loads(raw)["job_id"])
        session=self.app.sessions[self.cookie.split("=",1)[1]]
        self.assertEqual(len(session.comparison_seen),3)
        _,_,raw=self.post("/api/compare",{"draft_id":draft["draft_id"]})
        result=self.wait(json.loads(raw)["job_id"])["result"]
        self.assertEqual(len(result["cards"]),1)

    def test_public_origin_cookie_and_cross_site_protection(self):
        self.server.allowed_hosts={"demo.example.test"}
        self.server.allowed_origins={"https://demo.example.test"}
        self.server.public_origin="https://demo.example.test"
        status,headers,raw=self.request("GET","/api/session",extra={"Host":"demo.example.test"})
        self.assertEqual(status,200);self.assertIn("Secure",headers["Set-Cookie"])
        self.assertEqual(self.request("GET","/",extra={"Host":"untrusted.invalid"})[0],403)
        self.assertEqual(self.request("GET","/healthz",extra={"Host":"127.0.0.1"})[0],200)
        with self.assertRaises(ValueError):create_server(0,self.app,host="0.0.0.0")
        with self.assertRaises(ValueError):create_server(0,self.app,public_origin="http://demo.example.test")

    def test_process_budget_window_resets_without_removing_limit(self):
        from unittest.mock import patch
        self.app.process_budget=1
        with patch("cityplay.web.network",return_value=Response(200,{},{})),patch("cityplay.web.time.sleep"):
            self.app.qloo_network("GET","synthetic.invalid",{})
            with self.assertRaises(Exception):self.app.qloo_network("GET","synthetic.invalid",{})
            self.app.network_window_started-=3601
            self.app.qloo_network("GET","synthetic.invalid",{})
            self.assertEqual(self.app.network_calls,1)

    def test_manual_interest_cannot_forward_a_model_credential_to_qloo(self):
        draft = self.parse()
        draft["intent"]["interests"][0]["query"] = "synthetic-model-key"
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "intent": draft["intent"]})
        job = self.wait(json.loads(raw)["job_id"])
        self.assertEqual(job["error"]["code"], "SENSITIVE_INPUT_REJECTED")
        self.assertEqual(next(iter(self.app.sessions.values())).qloo.calls, 0)

    def test_request_shape_size_and_nonfinite_numbers_rejected(self):
        self.assertEqual(self.post("/api/parse", {"query": "hello"})[0], 400)
        self.assertEqual(self.request("POST", "/api/parse", "x"*16001, self.cookie, self.csrf)[0], 413)
        self.assertEqual(self.request("POST", "/api/parse", '{"bad":NaN}', self.cookie, self.csrf)[0], 400)

    def test_ready_response_never_exposes_credentials(self):
        status, headers, raw = self.request("GET", "/api/session", cookie=self.cookie)
        self.assertNotIn(b"synthetic-qloo-key", raw); self.assertNotIn(b"synthetic-model-key", raw)
        self.assertIn("HttpOnly", headers["Set-Cookie"]); self.assertIn("SameSite=Strict", headers["Set-Cookie"])

    def test_area_city_mismatch_and_unconfirmed_again(self):
        status, _, raw = self.post("/api/parse", {"query": "public interest", "city": "new_york", "area": {"lat": 31.23, "lon": 121.48}})
        job = self.wait(json.loads(raw)["job_id"])
        self.assertEqual(job["error"]["code"], "AREA_CITY_MISMATCH")
        draft = self.parse()
        status, _, raw = self.post("/api/discover", {"draft_id": draft["draft_id"], "again": True})
        job = self.wait(json.loads(raw)["job_id"])
        self.assertEqual(job["error"]["code"], "CONFIRM_INTENT_FIRST")


if __name__ == "__main__": unittest.main()
