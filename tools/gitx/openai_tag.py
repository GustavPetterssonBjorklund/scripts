import json
import re
from dataclasses import dataclass
from typing import Callable

from openai_commit import request_openai_text


ProgressCallback = Callable[[str], None]


@dataclass
class TagSuggestion:
    tag: str
    message: str
    bump: str


def generate_tag_suggestion(
    previous_tags: str,
    latest_tag: str,
    recent_commits: str,
    progress: ProgressCallback | None = None,
) -> TagSuggestion | None:
    if progress:
        progress("Building tag suggestion prompt...")

    prompt = build_tag_prompt(previous_tags, latest_tag, recent_commits)

    if progress:
        progress("Waiting for OpenAI to suggest a tag...")
    text = request_openai_text(prompt, max_output_tokens=260)
    if text is None:
        return None

    suggestion = parse_tag_suggestion(text)
    if suggestion is None:
        print("AI tag suggestion was not valid JSON.")
        return None

    if progress:
        progress("Received AI tag suggestion.")
    return suggestion


def build_tag_prompt(previous_tags: str, latest_tag: str, recent_commits: str) -> str:
    return (
        "Suggest the next annotated git version tag from the recent commits.\n"
        "Return only JSON with string keys: tag, bump, message.\n"
        "Do not wrap the JSON in markdown or explanation.\n"
        "Use semantic versioning. Preserve the existing tag prefix, such as v, if one exists.\n"
        "Choose bump as major, minor, or patch.\n"
        "The message should be a concise annotated tag message with 2-4 bullet points.\n"
        "Prefer patch for fixes and internal changes, minor for user-facing features, "
        "and major only for breaking changes.\n"
        f"\nLatest tag:\n{latest_tag or 'none'}\n"
        f"\nRecent tags:\n{previous_tags}\n"
        f"\nRecent commits since latest tag:\n{recent_commits}\n"
    )


def parse_tag_suggestion(text: str) -> TagSuggestion | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    tag = str(data.get("tag", "")).strip()
    bump = str(data.get("bump", "")).strip().lower()
    message = str(data.get("message", "")).strip()
    if not tag or not message or bump not in ("major", "minor", "patch"):
        return None
    return TagSuggestion(tag=tag, message=message, bump=bump)
