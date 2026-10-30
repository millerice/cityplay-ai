"""CLI entry point: python -m cityplay. Results are private by default."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from .config import ROOT, Settings
from .engine import DiscoveryEngine
from .intent import Area, Intent, ModelIntentParser
from .transport import DeepSeekClient, QlooClient, ServiceError


def save_private(path, value, settings):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Unsafe output path")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    content = settings.redact(json.dumps(value, ensure_ascii=False, indent=2))
    # Refuse overwrites to preserve earlier evidence, including failures.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Natural language, parsed by DeepSeek; omit personal identifiers")
    source.add_argument("--input", type=Path, help="Structured intent/request JSON, no credentials")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius-m", type=int, default=20000)
    parser.add_argument("--credentials", type=Path, help="Private .env file; defaults to .env.local")
    from .models import MODEL_BY_ID
    parser.add_argument("--model", choices=sorted(MODEL_BY_ID))
    args = parser.parse_args(argv)
    try:
        settings = Settings.load(args.credentials)
        if args.query and any(secret and secret in args.query for secret in [settings.qloo_key, settings.deepseek_key]):
            raise ServiceError("SENSITIVE_INPUT_REJECTED")
        model = DeepSeekClient(settings.deepseek_key, args.model or settings.model)
        if args.query:
            intent = ModelIntentParser(model).parse(args.query)
            area = Area(args.lat, args.lon, args.radius_m) if args.lat is not None and args.lon is not None else None
            seen, selections = [], {}
        else:
            data = json.loads(args.input.read_text())
            if not isinstance(data, dict) or set(data) - {"intent", "area", "seen_ids", "selections"}:
                raise ValueError("Unsupported request fields")
            intent = Intent.from_dict(data.get("intent"))
            area = Area(**data["area"]) if data.get("area") else None
            seen, selections = data.get("seen_ids", []), data.get("selections", {})
            if not isinstance(selections, dict):
                raise ValueError("Selections must be an object")
        client = QlooClient(settings.qloo_key)
        if any(secret and secret in interest.query for secret in [settings.qloo_key, settings.deepseek_key] for interest in intent.interests):
            raise ServiceError("SENSITIVE_INPUT_REJECTED")
        result = DiscoveryEngine(client).run(intent, area, seen_ids=seen, selections=selections)
        result["model_tools"] = model.trace
        output = ROOT / ".qloo-private" / "stage2" / (result["run_id"] + ".json")
        save_private(output, result, settings)
        print(json.dumps({"status": result["status"], "cards": len(result["cards"]),
                          "qloo_calls": client.calls, "website_verification": [x["verification"]["identity"] for x in result["cards"]],
                          "evidence_file": str(output)}, ensure_ascii=False))
        return 1 if result["status"] == "error" else 0
    except ServiceError as error:
        print(json.dumps({"status": "error", "code": error.code, "http_status": error.status}))
        return 1
    except (ValueError, TypeError, OSError):
        print(json.dumps({"status": "error", "code": "INVALID_INPUT_OR_LOCAL_CONFIGURATION"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
