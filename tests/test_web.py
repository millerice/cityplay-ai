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
