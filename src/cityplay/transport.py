"""Fixed-origin credential transport; no redirects, bounded reads and retries."""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from .config import QLOO_BASE, DEEPSEEK_BASE


class ServiceError(Exception):
    def __init__(self, code: str, *, retryable=False, status=None, details=None):
        super().__init__(code)  # Never return upstream response bodies or credentials.
        self.code, self.retryable, self.status = code, retryable, status
        self.details = details


@dataclass
class Response:
    status: int
    headers: dict
    data: dict


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def network(method, url, headers, body=None, timeout=20):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(5 * 1024 * 1024 + 1)
            status, response_headers = response.status, {k.lower(): v for k, v in response.headers.items()}
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ServiceError("NETWORK_TIMEOUT_OR_UNAVAILABLE", retryable=True) from None
    if len(raw) > 5 * 1024 * 1024:
        raise ServiceError("RESPONSE_TOO_LARGE")
    if status != 200:
        return Response(status, response_headers, {})
    try:
        parsed = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ServiceError("INVALID_JSON_RESPONSE") from None
    if not isinstance(parsed, dict):
        raise ServiceError("INVALID_RESPONSE_SHAPE")
    return Response(status, response_headers, parsed)


class QlooClient:
    PATHS = {"/search", "/v2/tags", "/v2/insights"}

    def __init__(self, key, *, sender=network, sleep=time.sleep, clock=time.monotonic, max_calls=14):
        self._key, self._sender, self._sleep, self._clock = key, sender, sleep, clock
        self.max_calls, self.calls = max_calls, 0
        self.trace, self.cache, self.remaining = [], {}, None
        self._last = -float("inf")
        self._lock = threading.Lock()

    def get(self, path, params):
        if path not in self.PATHS:
            raise ServiceError("UNSUPPORTED_ENDPOINT")
        if not self._key:
            raise ServiceError("QLOO_AUTH_MISSING")
        if any(self._key in str(value) for value in params.values()):
            raise ServiceError("SENSITIVE_INPUT_REJECTED")
        encoded = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        url = QLOO_BASE + path + "?" + urllib.parse.urlencode(encoded)
        with self._lock:
            return self._get_locked(path, url, encoded)

    def _get_locked(self, path, url, params):
        safe_params = {k: str(v).replace(self._key, "[REDACTED]") for k, v in params.items()}
        # In-memory cache only; public code never contains real API responses.
        cached = self.cache.get(url)
        if cached and self._clock() - cached[0] < 300:
            self.trace.append({"tool": "qloo", "path": path, "query": safe_params, "cached": True})
            return cached[1]
        for attempt in range(2):
            if self.calls >= self.max_calls:
                raise ServiceError("CALL_BUDGET_EXHAUSTED")
            if self.remaining is not None and self.remaining <= 10:
                raise ServiceError("MONTHLY_QUOTA_RESERVE")
            self._sleep(max(0, 0.3 - (self._clock() - self._last)))
            self._last = self._clock()
            self.calls += 1
            started = self._clock()
            try:
                response = self._sender("GET", url, {"X-Api-Key": self._key, "Accept": "application/json"})
            except ServiceError as error:
                self.trace.append({"tool": "qloo", "path": path, "query": safe_params, "attempt": attempt + 1, "error": error.code})
                if attempt == 0 and error.retryable:
                    self._sleep(0.5)
                    continue
                raise
            self.trace.append({"tool": "qloo", "path": path, "query": safe_params, "attempt": attempt + 1,
                               "http_status": response.status, "duration_ms": round((self._clock()-started)*1000)})
            remaining = response.headers.get("x-month-ratelimit-remaining")
            if remaining is not None:
                try:
                    self.remaining = int(remaining)
                except ValueError:
                    pass
            if response.status == 200:
                if response.data.get("success") is False or response.data.get("errors"):
                    raise ServiceError("QLOO_RESPONSE_ERROR")
                self.cache[url] = (self._clock(), response.data)
                return response.data
            retryable = response.status in {429, 500, 502, 503, 504}
            delay = response.headers.get("retry-after", "0.5")
            try:
                delay = float(delay)
            except ValueError:
                delay = 3  # HTTP-date Retry-After is not retried synchronously.
            if attempt == 0 and retryable and 0 <= delay <= 2:
                self._sleep(delay)
                continue
            code = "QLOO_AUTH" if response.status in {401, 403} else "QLOO_RATE_LIMIT" if response.status == 429 else "QLOO_HTTP_ERROR"
            raise ServiceError(code, retryable=retryable, status=response.status)
        raise ServiceError("QLOO_UNAVAILABLE")


class DeepSeekClient:
    def __init__(self, key, model="deepseek-v4-pro", sender=network):
        self._key, self.model, self._sender = key, model, sender
        self.trace = []

    def parse_json(self, system, query):
        if not self._key:
            raise ServiceError("DEEPSEEK_AUTH_MISSING")
        if self._key in query:
            raise ServiceError("SENSITIVE_INPUT_REJECTED")
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": query}],
            "thinking": {"type": "disabled"}, "max_tokens": getattr(self, "max_tokens", 1200),
            "response_format": {"type": "json_object"}, "stream": False}).encode()
        response = self._sender("POST", DEEPSEEK_BASE + "/chat/completions",
                                {"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}, body, timeout=30)
        self.trace.append({"tool": "deepseek", "model": self.model, "http_status": response.status})
        if response.status != 200:
            raise ServiceError("DEEPSEEK_HTTP_ERROR", status=response.status)
        try:
            choice = response.data["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError()
            result = json.loads(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ServiceError("DEEPSEEK_INVALID_OUTPUT") from None
        self.trace[-1]["usage"] = {k: v for k, v in response.data.get("usage", {}).items()
                                  if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, int)}
        self.trace[-1]["response_model"] = response.data.get("model")
        return result
