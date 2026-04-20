import os
import getpass
from pathlib import Path


DEFAULT_CONFIG_PATH = "~/.config/gitx/config"


def setup_ai_config():
    path = config_path()
    existing = read_config()

    if existing.get("openai_api_key"):
        answer = input(f"{path} already has an OpenAI API key. Replace it? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Setup cancelled.")
            return 1

    api_key = getpass.getpass("OpenAI API key: ").strip()
    if not api_key:
        print("No API key entered. Setup cancelled.")
        return 1

    existing["openai_api_key"] = api_key
    existing.setdefault("ai_model", "gpt-5.4-nano")
    existing.setdefault("ai_max_diff_chars", "20000")

    try:
        parent_existed = path.parent.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed or path.parent == Path(DEFAULT_CONFIG_PATH).expanduser().parent:
            path.parent.chmod(0o700)
        content = "\n".join(f"{key}={value}" for key, value in existing.items()) + "\n"
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    except OSError as error:
        print(f"Failed to write gitx config at {path}: {error}")
        return 1

    print(f"Saved gitx AI config to {path}")
    return 0


def config_path():
    return Path(os.environ.get("GITX_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


def get_config_value(key):
    env_key = f"GITX_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]

    values = read_config()
    return values.get(key)


def get_openai_api_key():
    if "OPENAI_API_KEY" in os.environ:
        return os.environ["OPENAI_API_KEY"]
    return get_config_value("openai_api_key")


def read_config():
    path = config_path()
    if not path.exists():
        return {}

    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        print(f"Failed to read gitx config at {path}: {error}")
        return {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"Ignoring invalid gitx config line: {line}")
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values
