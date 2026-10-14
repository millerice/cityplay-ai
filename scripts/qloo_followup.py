"""Follow up after qloo_poc.py: resolve reviewed candidates and inspect raw HTTP.

No invented IDs: select the artist Miles Davis and the 1982 movie Blade Runner
from private resolver results. Tags must match exact reviewed names and types.
"""
import datetime
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from qloo_poc import BASE, ROOT, private_write, read_values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never send a credential to a redirected origin.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--focus", action="store_true", help="Test hard venue tag filters separately")
    parser.add_argument("--retry-timeouts", action="store_true", help="One bounded retry of prior transport failures, timeout 45s")
    parser.add_argument("--empty-only", action="store_true", help="Verify a documented empty-query path")
    parser.add_argument("--point", action="store_true", help="Compare candidates within 20km of a returned city point")
    args = parser.parse_args()
    local = ROOT / ".env.local"
    values = read_values(local)
    key = os.environ.get("QLOO_API_KEY") or values.get("QLOO_API_KEY") or values.get("APIKey")
    if not key:
        print("MISSING_CREDENTIAL")
        return 4
    local.chmod(0o600)
    directory = ROOT / ".qloo-private"
    if directory.is_symlink():
        raise RuntimeError("Unsafe evidence directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)

    def load(name):
        return json.loads((directory / (name + ".json")).read_text())["output"]

    def select_entity(name, subtype, year=None):
        candidates = load(name)["resolution"]["issues"][0]["candidates"]
        matches = [x for x in candidates if x["type"] == subtype and
                   (year is None or x.get("release_year") == year)]
        if len(matches) != 1:
            raise RuntimeError("Candidate remains ambiguous; manual review required")
        return matches[0]["id"]

    def select_tag(case, name, tag_type):
        matches = [x for x in load(case)["results"] if x["name"].strip() == name and x["type"] == tag_type]
        if len(matches) != 1:
            raise RuntimeError("Tag remains ambiguous; manual review required")
        return matches[0]["id"]

    miles = select_entity("jazz-to-movie", "urn:entity:artist")
    blade = select_entity("scifi-to-artist", "urn:entity:movie", 1982)
    jazz = select_tag("tags-1", "Jazz", "urn:tag:genre:music")
    bookstore = select_tag("tags-2", "Independent Bookstores", "urn:tag:interests:qloo")
    coffee = select_tag("tags-4", "Coffee", "urn:tag:cuisine:qloo")
    setting = select_tag("tags-2", "Independent Bookstore", "urn:tag:setting:qloo")
    cases = [
        ("resolved-jazz-to-movie", "/v2/insights", {"filter.type": "urn:entity:movie", "signal.interests.entities": miles, "take": 5}),
        ("resolved-scifi-to-artist", "/v2/insights", {"filter.type": "urn:entity:artist", "signal.interests.entities": blade, "take": 5}),
    ]
    for city, slug in [("Shanghai, China", "shanghai"), ("New York, NY", "new-york")]:
        base = {"filter.type": "urn:entity:place", "filter.location.query": city,
                "filter.location.radius": 0, "take": 5}
        cases.append((slug + "-raw-baseline", "/v2/insights", base))
        for label, signal_name, signal in [
            ("miles", "signal.interests.entities", miles),
            ("jazz-tag", "signal.interests.tags", jazz),
            ("bookstore-tag", "signal.interests.tags", bookstore),
            ("coffee-tag", "signal.interests.tags", coffee),
        ]:
            cases.append((slug + "-raw-" + label, "/v2/insights", dict(base, **{signal_name: signal})))
    empty_case = ("empty-tag-query-valid", "/v2/tags", {"filter.query": "cityplay_nonexistent_9a782e", "feature.semantic_search": False, "take": 1})
    cases += [empty_case]
    if args.focus:
        cases = []
        for city, slug in [("Shanghai, China", "shanghai"), ("New York, NY", "new-york")]:
            for label, tag in [("bookstore", setting), ("coffee", coffee)]:
                cases.append((slug + "-filter-" + label, "/v2/insights", {
                    "filter.type": "urn:entity:place", "filter.location.query": city,
                    "filter.location.radius": 0, "filter.tags": tag,
                    "signal.interests.entities": miles, "take": 5}))
    if args.retry_timeouts:
        previous = json.loads((directory / "followup-summary.json").read_text())["records"]
        failed = {row["case"] for row in previous if row.get("status") == "transport_or_parse_error"}
        cases = [case for case in cases if case[0] in failed]
    if args.empty_only:
        cases = [empty_case]
    if args.point:
        cases = []
        for slug in ["shanghai", "new-york"]:
            source = load(slug + "-raw-baseline")["results"]["entities"][0]["location"]
            for label, extra in [
                ("baseline", {}), ("miles", {"signal.interests.entities": miles}),
                ("bookstore", {"signal.interests.entities": miles, "filter.tags": setting}),
                ("coffee", {"signal.interests.entities": miles, "filter.tags": coffee}),
            ]:
                cases.append((slug + "-point-" + label, "/v2/insights", {
                    "filter.type": "urn:entity:place", "filter.location": f"POINT({source['lon']} {source['lat']})",
                    "filter.location.radius": 20000, "take": 5, **extra}))
    opener = urllib.request.build_opener(NoRedirect)
    summary = []
    for name, endpoint, params in cases:
        encoded = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        url = BASE + endpoint + "?" + urllib.parse.urlencode(encoded)
        start = time.monotonic()
        request = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
        try:
            try:
                response = opener.open(request, timeout=45 if args.retry_timeouts else 20)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.status
                headers = {k: v for k, v in response.headers.items()
                           if any(x in k.lower() for x in ["ratelimit", "rate-limit", "retry-after", "quota", "request-id"])}
                body = response.read(5 * 1024 * 1024 + 1)
            if len(body) > 5 * 1024 * 1024:
                raise ValueError("Response size limit exceeded")
            text = body.decode().replace(key, "[REDACTED]")
            result = json.loads(text)
            private_write(directory / (name + ("-retry" if args.retry_timeouts else "") + ".json"), {"method": "GET", "endpoint": endpoint,
                          "params": params, "http_status": status, "headers": headers, "output": result})
            records = result.get("results", {})
            count = None
            if isinstance(records, dict):
                for field in ["entities", "tags"]:
                    if isinstance(records.get(field), list):
                        count = len(records[field])
            row = {"case": name, "http_status": status, "count": count,
                   "elapsed_ms": round((time.monotonic() - start) * 1000)}
        except (urllib.error.URLError, TimeoutError, ValueError):
            row = {"case": name, "status": "transport_or_parse_error",
                   "elapsed_ms": round((time.monotonic() - start) * 1000)}
        summary.append(row)
        print(json.dumps(row), flush=True)
        if row.get("http_status") in [401, 403, 429]:
            break
    summary_name = "point-summary.json" if args.point else "empty-summary.json" if args.empty_only else "retry-summary.json" if args.retry_timeouts else "focus-summary.json" if args.focus else "followup-summary.json"
    private_write(directory / summary_name, {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "records": summary})
    return 0 if any(x.get("http_status") == 200 for x in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
