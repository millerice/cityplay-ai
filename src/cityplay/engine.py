"""Explicit discovery state machine with auditable gates and conservative cards."""
from dataclasses import asdict
from collections import Counter
import math
import re
import uuid
from datetime import datetime, timezone
from .intent import Intent, Area
from .transport import ServiceError
from .verify import WebsiteVerifier, normalized

PUBLIC_CATEGORIES = {
    "bookstore": {"book store", "bookstore", "comic book store"},
    "coffee": {"cafe", "coffee shop", "coffee roastery"},
    "live_music": {"live music venue", "jazz club"},
    "park": {"park", "city park"},
    "museum": {"museum", "art museum", "history museum", "modern art museum"},
}
EXCLUDED_GENRES = {"hotel": {"hotel"}, "mall": {"shopping mall", "mall"},
                   "recording_studio": {"recording studio"}, "tourist_attraction": {"tourist attraction"}}
# Reviewed name/type selections from PoC, NOT hardcoded Qloo IDs.
FILTER_LOOKUPS = {"bookstore": ("bookstore", "Book store", "urn:tag:category:place"),
                  "coffee": ("coffee", "Coffee", "urn:tag:cuisine:qloo")}
TAG_LOOKUPS = {"bookstore": ("Book store", "urn:tag:category:place"),"jazz": ("Jazz", "urn:tag:genre:music"),
               "science fiction": ("Science Fiction", "urn:tag:genre:qloo"),
               "coffee": ("Coffee", "urn:tag:cuisine:qloo"),
               "indie bookstore": ("Independent Bookstores", "urn:tag:interests:qloo")}


def result_array(data, kind):
    results = data.get("results")
    if isinstance(results, list):
        return [x for x in results if isinstance(x, dict)]
    if not isinstance(results, dict) or not isinstance(results.get(kind), list):
        raise ServiceError("QLOO_RESPONSE_SHAPE")
    return [x for x in results[kind] if isinstance(x, dict)]


def distance_m(area, location):
    if not isinstance(location, dict):
        return None
    lat, lon = location.get("lat"), location.get("lon")
    if type(lat) not in {float, int} or type(lon) not in {float, int} or not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    a, b = map(math.radians, [area.lat, lat])
    dl = math.radians(lon - area.lon)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(dl/2)**2
    return round(6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h)))))


def candidate_type(entity):
    direct = entity.get("subtype") or entity.get("type")
    if isinstance(direct, str) and direct != "urn:entity":
        return direct
    values = entity.get("types")
    if isinstance(values, list):
        return next((value for value in values if isinstance(value, str) and value.startswith("urn:entity:")), None)
    return None


class ResolutionNeeded(Exception):
    def __init__(self, field, query, candidates):
        self.question = {"field": field, "query": query, "reason": "ambiguous_or_not_found",
                         "choices": [{"id": x.get("entity_id") or x.get("id"), "name": x.get("name"),
                                      "type": candidate_type(x),
                                      "release_year": (x.get("properties") or {}).get("release_year") if isinstance(x.get("properties"), dict) else None}
                                     for x in candidates]}


class DiscoveryEngine:
    def __init__(self, qloo, verifier=None):
        self.qloo = qloo
        self.verifier = verifier or WebsiteVerifier()

    def run(self, intent: Intent, area: Area | None, *, seen_ids=None, selections=None, on_progress=None, independent_bookstore=False, allow_no_signals=False):
        if seen_ids is not None and (not isinstance(seen_ids, list) or len(seen_ids) > 100 or any(not isinstance(x, str) for x in seen_ids)):
            raise ValueError("Invalid seen_ids")
        if selections is not None and not isinstance(selections, dict):
            raise ValueError("Invalid selections")
        run_id = str(uuid.uuid4())
        trace, rejected, resolved_inputs = [], [], []
        qloo_start = len(self.qloo.trace)
        def transition(state, **details):
            trace.append({"state": state, **details})
            if on_progress:
                on_progress(state, details)
        def finish(status, cards=None, questions=None, error=None):
            tools = self.qloo.trace[qloo_start:]
            cached = any(x.get("cached") for x in tools)
            live = any(x.get("http_status") == 200 for x in tools)
            source = "mixed_qloo" if cached and live else "cached_qloo" if cached else "live_qloo" if live else "no_qloo_result"
            retrieved = sum(x.get("candidates", 0) for x in trace if x.get("state") == "TASTE_RETRIEVED")
            counts = dict(Counter(reason for item in rejected for reason in item["reason"].split(",")))
            empty_reason = None
            if status == "empty":
                empty_reason = "no_api_candidates" if not retrieved else "already_shown" if counts and set(counts) <= {"explicitly_seen", "duplicate"} else "filtered_candidates"
            return {"taste_inputs": resolved_inputs, "recommendation_mode": "category_baseline" if allow_no_signals else "cultural_taste", "diagnostics": {"retrieved_count": retrieved, "rejection_counts": counts, "empty_reason": empty_reason}, "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "status": status,
                    "source": source,
                    "intent": asdict(intent), "area": asdict(area) if area else None,
                    "scope": "explicit_coordinate_radius; not administrative city boundary",
                    "cards": cards or [], "questions": questions or [], "error": error,
                    "trace": trace, "tools": tools, "rejections": rejected}
        transition("INTENT_PARSED", parser=intent.parser)
        questions = list(intent.clarifications)
        if intent.city is None:
            questions.append("Choose New York or Shanghai.")
        if area is None:
            questions.append("Provide an explicitly chosen center latitude/longitude and radius.")
        if not intent.interests and not allow_no_signals:
            questions.append("Provide at least one public cultural interest.")
        if intent.strict_city:
            questions.append("Administrative city boundaries are not verified; choose a radius or provide a verified boundary service.")
        if intent.novelty_requested and not seen_ids:
            questions.append("Provide places already visited, or relax the requirement to guarantee something new.")
        if questions:
            transition("NEEDS_INPUT")
            return finish("needs_input", questions=questions)
        seen_ids, selections = set(seen_ids or []), selections or {}
        if len(seen_ids) > 100 or any(not isinstance(x, str) for x in seen_ids):
            raise ValueError("Invalid seen_ids")
        # Selections are only accepted when the chosen ID exists in the current lookup results.
        def resolve(items, field, query, expected_name=None, expected_type=None):
            valid = [x for x in items if isinstance(x.get("name"), str) and isinstance(x.get("entity_id") or x.get("id"), str)]
            choice = selections.get(field)
            if choice:
                selected = [x for x in valid if (x.get("entity_id") or x.get("id")) == choice]
            else:
                selected = [x for x in valid if normalized(x["name"]) == normalized(expected_name or query)]
            if expected_type:
                selected = [x for x in selected if candidate_type(x) == expected_type]
            if len(selected) != 1:
                raise ResolutionNeeded(field, query, valid)
            chosen = selected[0]
            if field.startswith("interests."):
                resolved_inputs.append({"query":query, "name":chosen["name"].strip(), "type":candidate_type(chosen), "id":chosen.get("entity_id") or chosen.get("id")})
            return chosen.get("entity_id") or chosen.get("id")

        def lookup_tag(query, field, name=None, kind=None):
            tags = result_array(self.qloo.get("/v2/tags", {"filter.query": query, "feature.semantic_search": True, "take": 5}), "tags")
            return resolve(tags, field, query, name, kind)

        try:
            entities, tags = [], []
            for index, interest in enumerate(intent.interests):
                field = f"interests.{index}"
                if interest.kind == "entity":
                    params = {"query": interest.query, "take": 5}
                    if interest.entity_type:
                        params["types"] = "urn:entity:" + interest.entity_type
                    items = result_array(self.qloo.get("/search", params), "entities")
                    entities.append(resolve(items, field, interest.query,
                                            expected_type="urn:entity:" + interest.entity_type if interest.entity_type else None))
                else:
                    name, kind = TAG_LOOKUPS.get(interest.query.lower(), (None, None))
                    tags.append(lookup_tag(interest.query, field, name, kind))
            groups = []
            for category in intent.categories or [None]:
                params = {"filter.type": "urn:entity:place", "take": 5,
                          "filter.location": f"POINT({area.lon} {area.lat})", "filter.location.radius": area.radius_m}
                if entities:
                    params["signal.interests.entities"] = ",".join(entities)
                if tags:
                    params["signal.interests.tags"] = ",".join(tags)
                if category in FILTER_LOOKUPS:
                    query, name, kind = FILTER_LOOKUPS[category]
                    if category == "bookstore" and (independent_bookstore or any(re.search(r"independent book|indie book|独立书店", x.query, re.I) for x in intent.interests)):
                        query, name, kind = "indie bookstore", "Independent Bookstore", "urn:tag:setting:qloo"
                    params["filter.tags"] = lookup_tag(query, "category." + category, name, kind)
                values = result_array(self.qloo.get("/v2/insights", params), "entities")
                groups.append((category, values))
            transition("TASTE_RETRIEVED", queries=len(groups), candidates=sum(len(x[1]) for x in groups))
        except ResolutionNeeded as issue:
            transition("NEEDS_INPUT")
            return finish("needs_input", questions=[issue.question])
        except ServiceError as error:
            transition("FAILED", error=error.code)
            return finish("error", error={"code": error.code, "retryable": error.retryable, "http_status": error.status})

        allowed = set().union(*PUBLIC_CATEGORIES.values())
        excluded = set().union(*(PUBLIC_CATEGORIES.get(x, EXCLUDED_GENRES.get(x, set())) for x in intent.exclude_categories))
        pool, duplicate_ids = [], set()
        for category, values in groups:
            for rank, entity in enumerate(values):
                identifier = entity.get("entity_id")
                props = entity.get("properties")
                if not isinstance(props, dict):
                    props = {}
                primary = props.get("primary_genre")
                genre = normalized(primary.get("name", "")) if isinstance(primary, dict) else ""
                distance = distance_m(area, entity.get("location"))
                reason = None
                if not isinstance(identifier, str) or not isinstance(entity.get("name"), str) or not entity["name"].strip():
                    reason = "missing_entity_identity"
                elif identifier in seen_ids:
                    reason = "explicitly_seen"
                elif identifier in duplicate_ids:
                    reason = "duplicate"
                elif entity.get("subtype") != "urn:entity:place":
                    reason = "not_place"
                elif genre in excluded:
                    reason = "excluded_category"
                elif genre not in (PUBLIC_CATEGORIES[category] if category else allowed):
                    reason = "unsuitable_or_unknown_category"
                elif props.get("is_closed") is True:
                    reason = "qloo_reports_closed"
                elif distance is None or distance > area.radius_m:
                    reason = "missing_or_outside_coordinates"
                elif not isinstance(props.get("address"), str) or not props["address"].strip():
                    reason = "missing_address"
                if reason:
                    rejected.append({"entity_id": identifier, "reason": reason})
                    continue
                duplicate_ids.add(identifier)
                pool.append({"entity": entity, "rank": rank, "category": category or genre, "distance": distance})
        # Inspect only the best 6 eligible candidates; do not crawl all returned websites.
        pool.sort(key=lambda x: x["rank"])
        checked = []
        for entry in pool[:6]:
            evidence = self.verifier.check(entry["entity"])
            blocked = []
            if intent.max_budget is not None and evidence.budget != "verified":
                blocked.append("budget_unverified")
            if intent.available_minutes is not None and evidence.visit_duration != "verified":
                blocked.append("visit_and_travel_time_unverified")
            if intent.open_now and evidence.hours != "verified":
                blocked.append("open_now_unverified")
            if blocked:
                rejected.append({"entity_id": entry["entity"]["entity_id"], "reason": ",".join(blocked)})
                continue
            entry["evidence"] = evidence
            checked.append(entry)
        transition("CANDIDATES_CHECKED", checked=min(len(pool), 6), eligible=len(checked),
                   operational_verification="incomplete; no live hours, costs, events or access proof")
        # Interleave per-query ranks; do not compare affinity numbers across distinct queries.
        checked.sort(key=lambda x: (x["rank"], x["evidence"].identity != "website_name_corroborated"))
        selected, deferred, counts = [], [], {}
        for entry in checked:
            label = entry["category"]
            if counts.get(label, 0) >= 2:
                deferred.append(entry)
                continue
            counts[label] = counts.get(label, 0) + 1
            selected.append(entry)
        # Explicit single-category request permits more than two of that category.
        if len(intent.categories) == 1:
            selected.extend(deferred)
        transition("RANKED", returned=min(3, len(selected)), strategy="query_rank_then_website_evidence_with_category_diversity")
        cards = []
        for entry in selected[:3]:
            entity, evidence = entry["entity"], entry["evidence"]
            affinity = (entity.get("query") or {}).get("affinity") if isinstance(entity.get("query"), dict) else None
            if type(affinity) not in {float, int} or not math.isfinite(affinity):
                affinity = None
            cards.append({"entity_id": entity["entity_id"], "name": entity["name"],
                          "category": entry["category"], "address": entity["properties"]["address"],
                          "location": entity["location"], "straight_line_distance_m": entry["distance"],
                          "affinity": affinity, "query_rank": entry["rank"] + 1,
                          "taste_inputs": resolved_inputs, "recommendation_mode": "category_baseline" if allow_no_signals else "cultural_taste",
                          "why": "Returned by Qloo Insights using the confirmed cultural interests; category and coordinate radius passed local checks.",
                          "novelty": "not_in_provided_seen_list" if seen_ids else "unknown_without_visit_history",
                          "verification": evidence.to_dict(), "certainty": "exploration_candidate; verify before visiting",
                          "sources": [{"provider": "Qloo", "endpoint": "/v2/insights", "scope": "candidate, address, coordinates and aggregate affinity"}] +
                                     ([{"provider": "Qloo-listed website", "url": evidence.website, "scope": evidence.identity + "; no operational validation"}] if evidence.website else [])})
        transition("PRESENTED", status="partial" if cards else "empty")
        return finish("partial" if cards else "empty", cards, questions=[] if cards else ["No candidates passed the requested gates; relax constraints or provide verified operational data."])
