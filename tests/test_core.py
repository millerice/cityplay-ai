"""Synthetic tests; no model credential, live API calls or copied Qloo data."""
import copy
import json
import math
import unittest
from cityplay.config import Settings
from cityplay.engine import DiscoveryEngine, candidate_type
from cityplay.intent import Area, Intent, ModelIntentParser
from cityplay.transport import QlooClient, DeepSeekClient, Response, ServiceError
from cityplay.verify import WebsiteVerifier, public_https_target


def intent(**overrides):
    return Intent.from_dict({"city": "new_york", "interests": [{"kind": "entity", "query": "SYNTHETIC ARTIST", "entity_type": "artist"}], **overrides})


def place(identifier="synthetic-a", genre="Book store", lat=0.001, affinity=0.5):
    return {"entity_id": identifier, "name": "Synthetic Bookshop " + identifier,
            "type": "urn:entity", "subtype": "urn:entity:place", "location": {"lat": lat, "lon": 0},
            "query": {"affinity": affinity}, "properties": {"address": "SYNTHETIC ADDRESS",
            "primary_genre": {"name": genre}, "website": "https://synthetic.invalid/"}}


class FakeQloo:
    def __init__(self, places=None, ambiguous=False):
        self.trace, self.calls = [], 0
        self.places, self.ambiguous = places if places is not None else [place()], ambiguous

    def get(self, path, params):
        self.calls += 1
        self.trace.append({"path": path, "query": params, "http_status": 200})
        if path == "/search":
            entity = {"entity_id": "synthetic-artist", "name": "SYNTHETIC ARTIST", "subtype": "urn:entity:artist"}
            return {"results": [entity, {**entity, "entity_id": "synthetic-other"}] if self.ambiguous else [entity]}
        if path == "/v2/tags":
            return {"results": {"tags": [{"id": "urn:tag:setting:synthetic:books", "name": "Independent Bookstore", "type": "urn:tag:setting:qloo"}, {"id": "urn:tag:category:synthetic:books", "name": "Book store", "type": "urn:tag:category:place"}]}}
        return {"success": True, "results": {"entities": copy.deepcopy(self.places)}}


def verifier():
    return WebsiteVerifier(fetch=lambda url: (url, "Synthetic Bookshop synthetic-a Synthetic Bookshop synthetic-b Synthetic Bookshop synthetic-c"))


class EngineTests(unittest.TestCase):
    def test_place_description_uses_only_actual_string_fields(self):
        for fields,expected in [({'short_description':'  Actual short intro  ','description':'Long intro'},'Actual short intro'),
                                ({'short_description':[],'description':'Actual full intro'},'Actual full intro'),
                                ({'description':{'invented':'no'}},None),
                                ({'description':'x'*1000},'x'*800)]:
            candidate=place();candidate['properties'].update(fields)
            result=DiscoveryEngine(FakeQloo([candidate]),verifier()).run(intent(),Area(0,0))
            self.assertEqual(result['cards'][0]['description'],expected)

    def test_name_normalization_does_not_replace_an_unrelated_work(self):
        from cityplay.engine import identity_name
        self.assertEqual(identity_name('迈克尔 杰克逊'),identity_name('迈克尔杰克逊'))
        self.assertNotEqual(identity_name('鲁滨孙漂流记'),identity_name('重生手记：一个癌症患者的康复之路'))

    def test_explanation_only_accepts_known_finite_contributors(self):
        from cityplay.engine import recommendation_evidence
        data={'query':{'explainability':{'signal.interests.entities':[
            {'entity_id':'known','score':0.7},{'entity_id':'invented','score':0.9},
            {'entity_id':'known','score':float('nan')},{'entity_id':'known','score':True}]}}}
        evidence=recommendation_evidence(data,[{'id':'known','name':'Synthetic Artist'}])
        self.assertEqual(evidence['contributors'],[{'name':'Synthetic Artist','score':0.7}])
        self.assertEqual(recommendation_evidence({},[])['status'],'unavailable')

    def test_nearby_feedback_reorders_only_eligible_qloo_candidates(self):
        q=FakeQloo([place('synthetic-a',lat=.03),place('synthetic-b',lat=.001),place('synthetic-c',genre='Hotel',lat=0)])
        r=DiscoveryEngine(q,verifier()).run(intent(categories=['bookstore']),Area(0,0),prefer_nearby=True)
        self.assertEqual([c['entity_id'] for c in r['cards']],['synthetic-b','synthetic-a'])

    def test_generic_and_independent_bookstore_filters_are_distinct(self):
        for independent, expected in [(False, "urn:tag:category:synthetic:books"), (True, "urn:tag:setting:synthetic:books")]:
            qloo = FakeQloo()
            DiscoveryEngine(qloo, verifier()).run(intent(categories=["bookstore"]), Area(0, 0), independent_bookstore=independent)
            query = next(x["query"] for x in qloo.trace if x["path"] == "/v2/insights")
            self.assertEqual(query["filter.tags"], expected)

    def test_empty_diagnostics_distinguish_absence_filtering_and_seen(self):
        scenarios = [([], None, "no_api_candidates", {}),
                     ([place(genre="Craft store")], None, "filtered_candidates", {"unsuitable_or_unknown_category":1}),
                     ([place()], ["synthetic-a"], "already_shown", {"explicitly_seen":1})]
        for places, seen, reason, counts in scenarios:
            result = DiscoveryEngine(FakeQloo(places), verifier()).run(intent(categories=["bookstore"]), Area(0, 0), seen_ids=seen)
            self.assertEqual(result["status"], "empty")
            self.assertEqual(result["diagnostics"]["empty_reason"], reason)
            self.assertEqual(result["diagnostics"]["retrieved_count"], len(places))
            self.assertEqual(result["diagnostics"]["rejection_counts"], counts)

    def test_baseline_uses_no_taste_signals_and_retains_filters(self):
        qloo = FakeQloo()
        values = intent(categories=["bookstore"])
        values.interests=[]
        result=DiscoveryEngine(qloo,verifier()).run(values,Area(0,0),allow_no_signals=True)
        query=next(x["query"] for x in qloo.trace if x["path"]=="/v2/insights")
        self.assertFalse(any(k.startswith("signal.interests") for k in query))
        self.assertIn("filter.tags",query)
        self.assertEqual(result["recommendation_mode"],"category_baseline")
        self.assertEqual(result["taste_inputs"],[])

    def test_actual_resolved_taste_is_attached_to_cards(self):
        result=DiscoveryEngine(FakeQloo(),verifier()).run(intent(categories=["bookstore"]),Area(0,0))
        self.assertEqual(result["taste_inputs"][0]["name"],"SYNTHETIC ARTIST")
        self.assertEqual(result["cards"][0]["taste_inputs"],result["taste_inputs"])

    def test_verified_category_subtypes_are_not_dropped(self):
        for category,genre in [("museum","History museum"),("museum","Modern art museum"),("live_music","Jazz club"),("bookstore","Comic book store")]:
            result=DiscoveryEngine(FakeQloo([place(genre=genre)]),verifier()).run(intent(categories=[category]),Area(0,0))
            self.assertEqual(len(result["cards"]),1)

    def test_cached_discovery_is_labeled_as_cached(self):
        fake = FakeQloo()
        def sender(method, url, headers, *args, **kwargs):
            import urllib.parse
            parsed = urllib.parse.urlsplit(url)
            params = {k: values[0] for k, values in urllib.parse.parse_qs(parsed.query).items()}
            return Response(200, {}, fake.get(parsed.path, params))
        client = QlooClient("synthetic-key", sender=sender, sleep=lambda seconds: None)
        engine = DiscoveryEngine(client, verifier())
        first = engine.run(intent(categories=["bookstore"]), Area(0, 0))
        second = engine.run(intent(categories=["bookstore"]), Area(0, 0))
        self.assertEqual(first["source"], "live_qloo")
        self.assertEqual(second["source"], "cached_qloo")
        self.assertEqual(client.calls, 3)
    def test_search_type_array_is_distinct_from_insights_subtype(self):
        self.assertEqual(candidate_type({"types": ["urn:entity:artist"]}), "urn:entity:artist")
        self.assertEqual(candidate_type({"type": "urn:entity", "subtype": "urn:entity:place"}), "urn:entity:place")
        self.assertIsNone(candidate_type({"types": ["unrelated"]}))
    def test_complete_chain_is_provisional_not_operationally_verified(self):
        qloo = FakeQloo([place(), place("synthetic-b"), place("synthetic-c")])
        result = DiscoveryEngine(qloo, verifier()).run(intent(categories=["bookstore"]), Area(0, 0, 1000))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["cards"]), 3)
        self.assertEqual([x["state"] for x in result["trace"]], ["INTENT_PARSED", "TASTE_RETRIEVED", "CANDIDATES_CHECKED", "RANKED", "PRESENTED"])
        self.assertEqual(result["cards"][0]["verification"]["identity"], "website_name_corroborated")
        self.assertEqual(result["cards"][0]["verification"]["hours"], "unverified")
        self.assertIn("unknown", result["cards"][0]["novelty"])

    def test_high_affinity_never_overrides_constraints(self):
        candidates = [place("studio", "Recording studio", affinity=1), place("far", lat=1, affinity=1), place("closed")]
        candidates[-1]["properties"]["is_closed"] = True
        result = DiscoveryEngine(FakeQloo(candidates), verifier()).run(intent(), Area(0, 0, 1000))
        self.assertEqual(result["cards"], [])
        self.assertEqual({x["reason"] for x in result["rejections"]}, {"unsuitable_or_unknown_category", "missing_or_outside_coordinates", "qloo_reports_closed"})

    def test_missing_budget_time_and_open_now_proof_blocks_cards(self):
        value = intent(max_budget={"amount": 50, "currency": "USD"}, available_minutes=180, open_now=True)
        result = DiscoveryEngine(FakeQloo(), verifier()).run(value, Area(0, 0, 1000))
        self.assertEqual(result["status"], "empty")
        reason = result["rejections"][0]["reason"]
        self.assertIn("budget_unverified", reason)
        self.assertIn("visit_and_travel_time_unverified", reason)
        self.assertIn("open_now_unverified", reason)

    def test_seen_and_duplicate_entities_are_removed(self):
        qloo = FakeQloo([place("seen"), place(), place()])
        result = DiscoveryEngine(qloo, verifier()).run(intent(), Area(0, 0, 1000), seen_ids=["seen"])
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["novelty"], "not_in_provided_seen_list")
        self.assertEqual({x["reason"] for x in result["rejections"]}, {"explicitly_seen", "duplicate"})

    def test_novelty_without_history_and_strict_city_require_input(self):
        qloo = FakeQloo()
        result = DiscoveryEngine(qloo).run(intent(novelty_requested=True, strict_city=True), Area(0, 0))
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(qloo.calls, 0)
        self.assertEqual(result["source"], "no_qloo_result")

    def test_ambiguous_entity_never_auto_selects_highest_popularity(self):
        qloo = FakeQloo(ambiguous=True)
        result = DiscoveryEngine(qloo).run(intent(), Area(0, 0))
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(len(result["questions"][0]["choices"]), 2)
        self.assertEqual(qloo.calls, 1)

    def test_confirmed_selection_must_be_one_of_current_candidates(self):
        qloo = FakeQloo(ambiguous=True)
        result = DiscoveryEngine(qloo, verifier()).run(intent(), Area(0, 0), selections={"interests.0": "invented-id"})
        self.assertEqual(result["status"], "needs_input")
        result = DiscoveryEngine(qloo, verifier()).run(intent(), Area(0, 0), selections={"interests.0": "synthetic-artist"})
        self.assertEqual(result["status"], "partial")

    def test_category_does_not_trust_interest_or_api_filter_alone(self):
        result = DiscoveryEngine(FakeQloo([place("hotel", "Hotel"), place()]), verifier()).run(intent(categories=["bookstore"]), Area(0, 0))
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["rejections"][0]["reason"], "unsuitable_or_unknown_category")

    def test_category_exclusions_and_missing_coordinates(self):
        candidate = place("no-location"); candidate.pop("location")
        result = DiscoveryEngine(FakeQloo([candidate, place()]), verifier()).run(intent(exclude_categories=["bookstore"]), Area(0, 0))
        self.assertEqual(result["cards"], [])

    def test_service_error_is_distinct_from_empty(self):
        class Failed(FakeQloo):
            def get(self, path, params):
                raise ServiceError("QLOO_RATE_LIMIT", retryable=True, status=429)
        result = DiscoveryEngine(Failed()).run(intent(), Area(0, 0))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["http_status"], 429)


class TransportTests(unittest.TestCase):
    def test_credential_is_never_accepted_as_a_query_parameter(self):
        client = self.client([])
        with self.assertRaises(ServiceError) as failure:
            client.get("/search", {"query": "synthetic-secret"})
        self.assertEqual(failure.exception.code, "SENSITIVE_INPUT_REJECTED")
        self.assertEqual(client.calls, 0)
    def client(self, responses, **kwargs):
        self.requests, self.sleeps = [], []
        def sender(*args, **options):
            self.requests.append(args)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return QlooClient("synthetic-secret", sender=sender, sleep=self.sleeps.append, **kwargs)

    def test_401_never_retries_or_leaks_key_in_trace(self):
        client = self.client([Response(401, {}, {})])
        with self.assertRaises(ServiceError) as failure:
            client.get("/v2/tags", {"filter.query": "jazz"})
        self.assertEqual(failure.exception.code, "QLOO_AUTH")
        self.assertEqual(client.calls, 1)
        self.assertNotIn("synthetic-secret", json.dumps(client.trace))

    def test_retry_429_once_respects_retry_after(self):
        client = self.client([Response(429, {"retry-after": "1"}, {}), Response(200, {}, {"results": {"tags": []}})])
        client.get("/v2/tags", {"feature.semantic_search": False})
        self.assertEqual(client.calls, 2)
        self.assertIn(1, self.sleeps)
        self.assertIn("feature.semantic_search=false", self.requests[0][1])

    def test_large_retry_after_does_not_busy_retry(self):
        client = self.client([Response(429, {"retry-after": "60"}, {})])
        with self.assertRaises(ServiceError):
            client.get("/v2/tags", {})
        self.assertEqual(client.calls, 1)

    def test_503_and_network_retry_are_bounded(self):
        for response in [Response(503, {}, {}), ServiceError("NETWORK_TIMEOUT_OR_UNAVAILABLE", retryable=True)]:
            client = self.client([response, response])
            with self.assertRaises(ServiceError):
                client.get("/v2/tags", {})
            self.assertEqual(client.calls, 2)

    def test_cache_and_call_budget_prevent_extra_requests(self):
        client = self.client([Response(200, {}, {"results": {"tags": []}})], max_calls=1)
        first = client.get("/v2/tags", {"filter.query": "jazz"})
        self.assertEqual(client.get("/v2/tags", {"filter.query": "jazz"}), first)
        with self.assertRaises(ServiceError):
            client.get("/v2/tags", {"filter.query": "coffee"})
        self.assertEqual(client.calls, 1)

    def test_monthly_reserve_and_unsupported_origin(self):
        client = self.client([Response(200, {"x-month-ratelimit-remaining": "10"}, {"results": {"tags": []}})])
        client.get("/v2/tags", {})
        with self.assertRaises(ServiceError):
            client.get("/search", {})
        with self.assertRaises(ServiceError):
            client.get("https://untrusted.invalid/", {})
        self.assertEqual(client.calls, 1)

    def test_deepseek_payload_is_json_only_and_bounded(self):
        captured = []
        def sender(*args, **kwargs):
            captured.append(args)
            return Response(200, {}, {"model": "synthetic-model", "choices": [{"finish_reason": "stop", "message": {"content": '{"city":null}'}}]})
        client = DeepSeekClient("synthetic-model-secret", sender=sender)
        self.assertEqual(client.parse_json("Return JSON", "synthetic query"), {"city": None})
        body = json.loads(captured[0][3])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["max_tokens"], 1200)
        self.assertNotIn("synthetic-model-secret", json.dumps(client.trace))


class VerificationAndIntentTests(unittest.TestCase):
    def test_ssrf_private_loopback_and_mixed_dns_rejected(self):
        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
        for url in ["http://localhost/", "http://10.0.0.1/", "file:///etc/passwd", "https://user:password@example.com/", "https://example.com:8080/", "https://example.com/"]:
            with self.assertRaises(ValueError):
                public_https_target(url, resolver)

    def test_name_match_does_not_prove_open_or_budget(self):
        evidence = verifier().check(place())
        self.assertEqual(evidence.identity, "website_name_corroborated")
        self.assertEqual(evidence.hours, "unverified")
        self.assertEqual(evidence.budget, "unverified")
        self.assertEqual(evidence.public_access, "unverified")

    def test_failed_website_is_not_exposed_as_safe_link(self):
        def fetch(url):
            raise ValueError("Unsafe target")
        evidence = WebsiteVerifier(fetch=fetch).check(place())
        self.assertIsNone(evidence.website)

    def test_invalid_model_field_and_coordinates_rejected(self):
        for value in [{"city": "new_york", "interests": [], "invented_place": "made up"},
                      {"city": "new_york", "interests": [{"kind": "entity", "query": "person@example.com"}]}]:
            with self.assertRaises(ValueError):
                Intent.from_dict(value)
        for lat in [math.nan, math.inf, 100]:
            with self.assertRaises(ValueError):
                Area(lat, 0)

    def test_model_cannot_silently_omit_explicit_time_or_budget(self):
        class Model:
            model = "synthetic"
            def parse_json(self, system, query):
                return {"city": "new_york", "interests": []}
        value = ModelIntentParser(Model()).parse("预算50美元，只有3小时")
        self.assertEqual(len(value.clarifications), 2)

    def test_model_omitted_open_now_boundary_and_exclusions_require_confirmation(self):
        class Model:
            model = "synthetic"
            def parse_json(self, system, query):
                return {"city": "new_york", "interests": []}
        value = ModelIntentParser(Model()).parse("纽约市内，必须现在营业，避免商场和酒店")
        self.assertEqual(len(value.clarifications), 4)

    def test_settings_repr_hides_both_credentials(self):
        self.assertNotIn("qloo-secret", repr(Settings("qloo-secret", "model-secret")))
        self.assertNotIn("model-secret", repr(Settings("qloo-secret", "model-secret")))


if __name__ == "__main__":
    unittest.main()
