import os
import getpass
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_CONFIG_PATH = "~/.config/gitx/config"
DEFAULT_PROJECTS_PATH = "~/.config/gitx/projects.toml"

@dataclass
class GitXConfig:
    openai_api_key: str | None = None
    ai_model: str = "gpt-5.4-mini"
    ai_max_diff_chars: int = 20000
    
    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "GitXConfig":
        openai_api_key_value = kwargs.get("openai_api_key")
        ai_model_value = kwargs.get("ai_model", "gpt-5.4-mini")
        ai_max_diff_chars_value = kwargs.get("ai_max_diff_chars", 20000)

        return cls(
            openai_api_key=str(openai_api_key_value) if openai_api_key_value is not None else None,
            ai_model=str(ai_model_value),
            ai_max_diff_chars=int(ai_max_diff_chars_value)
        )


@dataclass
class ProjectRules:
    path: Path
    rules: str
    rules_file: Path | None = None


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


def projects_config_path():
    return Path(os.environ.get("GITX_PROJECTS_CONFIG", DEFAULT_PROJECTS_PATH)).expanduser()


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


def get_project_rules(project_path: str | Path) -> Optional[ProjectRules]:
    try:
        import tomllib
    except ModuleNotFoundError:
        print("AI validation project config requires Python 3.11 or newer for TOML support.")
        return None

    path = projects_config_path()
    if not path.exists():
        return None

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"Failed to read gitx project config at {path}: {error}")
        return None

    entries = data.get("project", [])
    if not isinstance(entries, list):
        print(f"Invalid gitx project config at {path}: project must be a list.")
        return None

    current_path = Path(project_path).expanduser().resolve()
    matches: list[tuple[int, ProjectRules]] = []
    for entry in entries:
        rules = _project_rules_from_entry(entry, path.parent)
        if rules and _is_path_match(current_path, rules.path):
            matches.append((len(matches), rules))

    if not matches:
        return None

    return max(matches, key=lambda item: (len(item[1].path.parts), item[0]))[1]


def ensure_project_rules_file(project_path: str | Path) -> Optional[Path]:
    root = Path(project_path).expanduser().resolve()
    existing = get_project_rules(root)
    if existing and existing.rules_file:
        return existing.rules_file

    config_file = projects_config_path()
    config_dir = config_file.parent
    rules_file = _default_project_rules_file(root, config_dir)

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "projects").mkdir(parents=True, exist_ok=True)
        if not rules_file.exists():
            initial_rules = existing.rules if existing else _default_project_rules(root)
            rules_file.write_text(initial_rules.rstrip() + "\n", encoding="utf-8")

        relative_rules_file = rules_file.relative_to(config_dir)
        entry = (
            "\n"
            "[[project]]\n"
            f"path = {_toml_quote(str(root))}\n"
            f"rules_file = {_toml_quote(str(relative_rules_file))}\n"
        )
        with config_file.open("a", encoding="utf-8") as file:
            file.write(entry)
    except OSError as error:
        print(f"Failed to prepare gitx project rules at {config_file}: {error}")
        return None

    return rules_file


def _project_rules_from_entry(entry: Any, config_dir: Path) -> Optional[ProjectRules]:
    if not isinstance(entry, dict):
        print("Ignoring invalid gitx project entry: expected a table.")
        return None

    raw_path = entry.get("path")
    if not raw_path:
        print("Ignoring gitx project entry without a path.")
        return None

    rules_parts: list[str] = []
    inline_rules = entry.get("rules")
    if isinstance(inline_rules, str):
        rules_parts.append(inline_rules.strip())
    elif isinstance(inline_rules, list):
        rules_parts.extend(str(rule).strip() for rule in inline_rules if str(rule).strip())

    rules_file = entry.get("rules_file")
    if rules_file:
        rules_path = Path(str(rules_file)).expanduser()
        if not rules_path.is_absolute():
            rules_path = config_dir / rules_path
        try:
            rules_parts.append(rules_path.read_text(encoding="utf-8").strip())
        except OSError as error:
            print(f"Failed to read gitx project rules file at {rules_path}: {error}")
            return None

    rules = "\n".join(part for part in rules_parts if part).strip()
    if not rules:
        print(f"Ignoring gitx project entry for {raw_path}: no rules configured.")
        return None

    resolved_rules_file = None
    if rules_file:
        resolved_rules_file = Path(str(rules_file)).expanduser()
        if not resolved_rules_file.is_absolute():
            resolved_rules_file = config_dir / resolved_rules_file

    return ProjectRules(
        path=Path(str(raw_path)).expanduser().resolve(),
        rules=rules,
        rules_file=resolved_rules_file,
    )


def _is_path_match(current_path: Path, configured_path: Path) -> bool:
    return current_path == configured_path or configured_path in current_path.parents


def _default_project_rules_file(project_path: Path, config_dir: Path) -> Path:
    digest = hashlib.sha1(str(project_path).encode("utf-8")).hexdigest()[:10]
    return config_dir / "projects" / f"{project_path.name}-{digest}.md"


def _default_project_rules(project_path: Path) -> str:
    return (
        f"# gitx validation rules for {project_path}\n"
        "\n"
        "- Update docs when changing public CLI behavior.\n"
        "- Do not commit secrets, API keys, or local machine credentials.\n"
    )


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
