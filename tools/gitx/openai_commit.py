import json
import urllib.error
import urllib.request

from config import get_config_value, get_openai_api_key
from dataclasses import dataclass
from typing import Any, Optional
@dataclass
class OpenAIResponse:
    output_text: str | None = None
    used_truncated_diff: bool = False

def extract_response_text(data: dict[str, Any]) -> Optional[str]:
    if data.get("output_text"):
        return data["output_text"].strip()

    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def generate_commit_message(diff: str) -> Optional[OpenAIResponse]:
    api_key = get_openai_api_key()
    if not api_key:
        print("OpenAI API key is not set.")
        print("Set OPENAI_API_KEY or add openai_api_key to ~/.config/gitx/config.")
        return None

    model = get_config_value("ai_model") or "gpt-5.4-nano"
    try:
        max_diff_chars = int(get_config_value("ai_max_diff_chars") or "20000")
    except ValueError:
        print("ai_max_diff_chars must be an integer.")
        return None

    truncated = len(diff) > max_diff_chars
    diff = diff[:max_diff_chars]

    prompt = (
        "Generate a git commit message for the staged diff below.\n"
        "Return only the raw commit message text.\n"
        "Do not wrap it in quotes, markdown, JSON, code fences, or explanation.\n"
        "Do not include labels like 'Subject:' or 'Body:'.\n"
        "Use this exact format:\n"
        "activity(scope): short info\n"
        "\n"
        "- concise detail\n"
        "- concise detail\n"
        "The subject must be under 72 characters.\n"
        "The body must contain 2-4 concise bullet points with more detailed info.\n"
        "Choose activity from: feat, fix, docs, refactor, test, chore, build, ci, style, perf.\n"
        "Choose a concrete lowercase scope from the changed area, such as gitx, ai, tui, config, readme, nix, redact, copy, or ovpntmp.\n"
        "Use imperative mood and mention the user-visible behavior change.\n"
    )
    if truncated:
        prompt += "\nThe diff was truncated; summarize only the visible changes.\n"
    prompt += f"\nStaged diff:\n{diff}"

    payload = json.dumps({
        "model": model,
        "input": prompt,
        "max_output_tokens": 120,
    }).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"OpenAI API request failed: HTTP {error.code}")
        print(detail)
        return None
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"OpenAI API request failed: {error}")
        return None

    return OpenAIResponse(
        output_text=extract_response_text(data),
        used_truncated_diff=truncated
    )


def clean_commit_message(message: str) -> str:
    lines = message.strip().strip('"').splitlines()

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(line.rstrip() for line in lines)
