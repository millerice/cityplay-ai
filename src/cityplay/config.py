from dataclasses import dataclass, field
import os
from pathlib import Path
from .models import DEFAULT_MODEL_ID, MODEL_BY_ID

ROOT = Path(__file__).resolve().parents[2]
QLOO_BASE = "https://hackathon.api.qloo.com"
DEEPSEEK_BASE = "https://api.deepseek.com"


def local_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    path.chmod(0o600)
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    qloo_key: str = field(default="", repr=False)
    deepseek_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL_ID

    @classmethod
    def load(cls, path: Path | None = None):
        values = local_values(path or ROOT / ".env.local")
        def get(name):
            return os.environ.get(name) or values.get(name, "")
        model = get("DEEPSEEK_MODEL") or DEFAULT_MODEL_ID
        if model not in MODEL_BY_ID:
            raise ValueError("Unsupported model identifier")
        return cls(get("QLOO_API_KEY") or get("APIKey"), get("DEEPSEEK_API_KEY"), model)

    def redact(self, text: str) -> str:
        for secret in [self.qloo_key, self.deepseek_key]:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text
