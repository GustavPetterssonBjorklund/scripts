# scripts

Small CLI utilities packaged as a Nix flake.

## Usage

Run a tool directly:

```bash
nix run .#copy -- --help
nix run .#gitx -- -h
nix run .#ovpntmp
nix run .#redact -- --help
```

Build or install a package:

```bash
nix build .#gitx
nix profile install .#gitx
```

Open the development shell:

```bash
nix develop
```

## Layout

- `tools/<name>/`: source for each CLI utility
- `pkgs/<name>.nix`: Nix packaging for each utility
- `legacy/`: old installer-oriented scripts kept out of the main path

## Adding a New Utility

1. Add the source under `tools/<name>/`.
2. Add a package definition under `pkgs/<name>.nix`.
3. Export it from `flake.nix` under `packages` and `apps`.

## Included Utilities

- `gitx`: short aliases for common git commands
- `copy`: copy piped stdin, text arguments, or the previous tmux command transcript to the system clipboard
- `ovpntmp`: choose and run a temporary OpenVPN config from Downloads
- `redact`: inspect piped stdin, score likely sensitive values, and interactively replace them with `<redacted>`

### gitx AI commit messages

`gitx c --ai` generates a commit message from staged changes with the OpenAI Responses API, opens a small terminal approval screen, and commits only after approval.
Generated messages use `activity(scope): short info` with a short body for detail.
When the staged diff exceeds `ai_max_diff_chars`, gitx keeps a complete changed-file list and uses per-file excerpts so large early assets do not hide later code changes.
While waiting for OpenAI, the terminal UI shows the current stage of prompt preparation and response generation.

The default model is `gpt-5.4-nano`. Override it in `~/.config/gitx/config`:

```text
openai_api_key=your_api_key_here
ai_model=gpt-5.4-nano
ai_max_diff_chars=20000
```

Environment variables still take priority: `OPENAI_API_KEY`, `GITX_AI_MODEL`, `GITX_AI_MAX_DIFF_CHARS`, and `GITX_CONFIG`.

AI validation reads project-specific rules from `~/.config/gitx/projects.toml`.
The most specific matching path wins.
Run `gitx validate --edit-rules` to create or edit the rules file for the current repository.

```toml
[[project]]
path = "/home/gustav/Documents/github/scripts"
rules = [
  "Update README.md when changing public gitx command behavior.",
  "Keep tools/gitx stdlib-only unless the change explicitly justifies a dependency.",
  "Do not commit secrets, API keys, or local machine credentials.",
]
```

Rules can also live in a separate file, relative to `~/.config/gitx`:

```toml
[[project]]
path = "/home/gustav/Documents/github/scripts"
rules_file = "projects/scripts.md"
```

Override the project config path with `GITX_PROJECTS_CONFIG`.

Example:

```bash
copy
git rev-parse HEAD | nix run .#copy
cat .env | nix run .#redact
cat incident.log | nix run .#redact -- --yes
```
