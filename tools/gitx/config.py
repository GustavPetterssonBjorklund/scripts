import os
import getpass
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_CONFIG_PATH = "~/.config/gitx/config"

@dataclass
class GitXConfig:
    openai_api_key: str | None = None
    ai_model: str = "gpt-5.4-nano"
    ai_max_diff_chars: int = 20000
    
    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "GitXConfig":
        openai_api_key_value = kwargs.get("openai_api_key")
        ai_model_value = kwargs.get("ai_model", "gpt-5.4-nano")
        ai_max_diff_chars_value = kwargs.get("ai_max_diff_chars", 20000)

        return cls(
            openai_api_key=str(openai_api_key_value) if openai_api_key_value is not None else None,
            ai_model=str(ai_model_value),
            ai_max_diff_chars=int(ai_max_diff_chars_value)
        )

def setup_ai_config():
    path = config_path()
    existing: GitXConfig | None = read_config()

    if existing and existing.openai_api_key:
        answer = input(f"{path} already has an OpenAI API key. Replace it? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Setup cancelled.")
            return 1

    api_key = getpass.getpass("OpenAI API key: ").strip()
    if not api_key:
        print("No API key entered. Setup cancelled.")
        return 1

    if existing:
        existing.openai_api_key = api_key
    else:
        existing = GitXConfig(openai_api_key=api_key)

    try:
        parent_existed = path.parent.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed or path.parent == Path(DEFAULT_CONFIG_PATH).expanduser().parent:
            path.parent.chmod(0o700)
        content = "\n".join(f"{key}={value}" for key, value in existing.__dict__.items()) + "\n"
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    except OSError as error:
        print(f"Failed to write gitx config at {path}: {error}")
        return 1

    print(f"Saved gitx AI config to {path}")
    return 0


def config_path():
    return Path(os.environ.get("GITX_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


def get_config_value(key: str) -> Optional[str]:
    env_key = f"GITX_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]

    values: GitXConfig | None = read_config()
    return values.__dict__.get(key) if values else None


def get_openai_api_key() -> Optional[str]:
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    return get_config_value("openai_api_key")


def read_config() -> Optional[GitXConfig]:
    path = config_path()
    if not path.exists():
        return

    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        print(f"Failed to read gitx config at {path}: {error}")
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"Ignoring invalid gitx config line: {line}")
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return GitXConfig.from_kwargs(**values)
