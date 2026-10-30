"""Built-in OpenAI-compatible chat model presets.

The browser only chooses a preset id. Base URLs stay server-side so callers
cannot point the web process at an arbitrary host.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPreset:
    id: str
    label: str
    label_zh: str
    provider: str
    provider_zh: str
    api_model: str
    base_url: str
    thinking_disable: bool = False


# Curated domestic + international chat endpoints that speak /chat/completions.
MODEL_PRESETS: tuple[ModelPreset, ...] = (
    ModelPreset("deepseek-chat", "DeepSeek Chat", "DeepSeek Chat", "DeepSeek", "DeepSeek", "deepseek-chat", "https://api.deepseek.com", True),
    ModelPreset("deepseek-reasoner", "DeepSeek Reasoner", "DeepSeek Reasoner", "DeepSeek", "DeepSeek", "deepseek-reasoner", "https://api.deepseek.com", True),
    ModelPreset("deepseek-v4-pro", "DeepSeek V4 Pro", "DeepSeek V4 Pro", "DeepSeek", "DeepSeek", "deepseek-v4-pro", "https://api.deepseek.com", True),
    ModelPreset("deepseek-v4-flash", "DeepSeek V4 Flash", "DeepSeek V4 Flash", "DeepSeek", "DeepSeek", "deepseek-v4-flash", "https://api.deepseek.com", True),
    ModelPreset("deepseek-flash", "DeepSeek Flash", "DeepSeek Flash", "DeepSeek", "DeepSeek", "deepseek-flash", "https://api.deepseek.com", True),
    ModelPreset("gpt-4o-mini", "GPT-4o mini", "GPT-4o mini", "OpenAI", "OpenAI", "gpt-4o-mini", "https://api.openai.com/v1"),
    ModelPreset("gpt-4o", "GPT-4o", "GPT-4o", "OpenAI", "OpenAI", "gpt-4o", "https://api.openai.com/v1"),
    ModelPreset("gpt-4.1-mini", "GPT-4.1 mini", "GPT-4.1 mini", "OpenAI", "OpenAI", "gpt-4.1-mini", "https://api.openai.com/v1"),
    ModelPreset("gpt-4.1", "GPT-4.1", "GPT-4.1", "OpenAI", "OpenAI", "gpt-4.1", "https://api.openai.com/v1"),
    ModelPreset("qwen-plus", "Qwen Plus", "通义千问 Plus", "Qwen", "阿里云通义", "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ModelPreset("qwen-turbo", "Qwen Turbo", "通义千问 Turbo", "Qwen", "阿里云通义", "qwen-turbo", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ModelPreset("qwen-max", "Qwen Max", "通义千问 Max", "Qwen", "阿里云通义", "qwen-max", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ModelPreset("moonshot-v1-8k", "Kimi 8K", "Kimi 8K", "Moonshot", "月之暗面", "moonshot-v1-8k", "https://api.moonshot.cn/v1"),
    ModelPreset("moonshot-v1-32k", "Kimi 32K", "Kimi 32K", "Moonshot", "月之暗面", "moonshot-v1-32k", "https://api.moonshot.cn/v1"),
    ModelPreset("moonshot-v1-128k", "Kimi 128K", "Kimi 128K", "Moonshot", "月之暗面", "moonshot-v1-128k", "https://api.moonshot.cn/v1"),
    ModelPreset("glm-4-flash", "GLM-4 Flash", "智谱 GLM-4 Flash", "Zhipu", "智谱", "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4"),
    ModelPreset("glm-4-plus", "GLM-4 Plus", "智谱 GLM-4 Plus", "Zhipu", "智谱", "glm-4-plus", "https://open.bigmodel.cn/api/paas/v4"),
    ModelPreset("llama-3.3-70b-versatile", "Llama 3.3 70B", "Llama 3.3 70B", "Groq", "Groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
)

MODEL_BY_ID = {preset.id: preset for preset in MODEL_PRESETS}
DEFAULT_MODEL_ID = "deepseek-v4-pro"
ALLOWED_MODEL_BASES = frozenset(preset.base_url for preset in MODEL_PRESETS)


def resolve_model(model_id: str | None) -> ModelPreset:
    preset = MODEL_BY_ID.get(model_id or "")
    if preset:
        return preset
    return MODEL_BY_ID[DEFAULT_MODEL_ID]


def public_model_catalog() -> list[dict[str, str]]:
    return [{
        "id": preset.id,
        "label": preset.label,
        "label_zh": preset.label_zh,
        "provider": preset.provider,
        "provider_zh": preset.provider_zh,
    } for preset in MODEL_PRESETS]
