"""Bounded Qloo CLI PoC. Credentials never enter argv or console output.

Usage: python3 scripts/qloo_poc.py --cli /path/to/qloo
Raw responses are PRIVATE: .qloo-private/ (never commit or publish).
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://hackathon.api.qloo.com"


def read_values(path):
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
    return values


def private_write(path, data):
    # Reject symlinks and ensure permissions before writing any response.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(data, output, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default=shutil.which("qloo"))
    args = parser.parse_args()
    local = ROOT / ".env.local"
    if local.is_file():
        local.chmod(0o600)
    values = read_values(local)
    config_root = Path(os.environ.get("QLOO_HOME", str(Path.home() / ".qloo"))).expanduser()
    config = read_values(config_root / "config")
    key = os.environ.get("QLOO_API_KEY") or values.get("QLOO_API_KEY") or values.get("APIKey") or config.get("api_key")
    if not key:
        print("MISSING_CREDENTIAL: privately configure .env.local or QLOO_API_KEY; no API request sent.")
        return 4
    if not args.cli or not Path(args.cli).is_file():
        print("MISSING_CLI: install @qloo/qloo-harness >= 0.1.26, or supply --cli.")
        return 2
    env = dict(os.environ, QLOO_API_KEY=key, QLOO_BASE_URL=BASE, QLOO_TRUSTED_BASE_URL=BASE)
    # Isolate harness state (including possible traces) from other projects.
    private = ROOT / ".qloo-private"
    if private.is_symlink():
        print("UNSAFE_PRIVATE_DIRECTORY")
        return 2
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    env["QLOO_HOME"] = str(private / "harness")
    cases = [("tags-" + str(i), "find_tags", {"query": q, "limit": 5})
             for i, q in enumerate(["jazz", "indie bookstore", "science fiction", "coffee"], 1)]
    cases += [
        ("jazz-to-movie", "recommend", {"target_type": "movie", "signals": ["Miles Davis"], "limit": 5}),
        ("scifi-to-artist", "recommend", {"target_type": "artist", "signals": ["Blade Runner"], "limit": 5}),
    ]
    for city in ["Shanghai, China", "New York, NY"]:
        slug = "shanghai" if city.startswith("Shanghai") else "new-york"
        cases += [
            (slug + "-baseline", "recommend", {"target_type": "place", "signal_location": city, "filter_location": city, "limit": 5}),
            (slug + "-jazz", "recommend", {"target_type": "place", "signals": ["Miles Davis"], "filter_location": city, "limit": 5}),
        ]
    records = []
    for name, operation, inputs in cases:
        start = time.monotonic()
        command = [args.cli, "exec", operation, "--input", json.dumps(inputs)]
        try:
            proc = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
            stdout = proc.stdout.replace(key, "[REDACTED]")
            stderr = proc.stderr.replace(key, "[REDACTED]")
            try:
                result = json.loads(stdout)
            except json.JSONDecodeError:
                result = {"status": "invalid_json"}
            private_write(private / (name + ".json"), {"input": inputs, "output": result, "stderr": stderr})
            record = {"case": name, "operation": operation, "input": inputs,
                      "exit_code": proc.returncode, "status": result.get("status"),
                      "result_count": result.get("result_count"),
                      "elapsed_ms": round((time.monotonic() - start) * 1000),
                      "error_code": (result.get("error") or {}).get("code")}
        except subprocess.TimeoutExpired:
            record = {"case": name, "status": "timeout", "elapsed_ms": 60000}
        records.append(record)
        # Only locally computed statistics are printed; never raw response data.
        print(json.dumps(record, ensure_ascii=False))
        if record.get("error_code") == "QLOO_AUTH" or record.get("exit_code") == 4:
            break
    private_write(private / "summary.json", {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "records": records})
    return 0 if any(r.get("status") == "ok" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
