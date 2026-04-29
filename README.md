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

`gitx c <message>` commits with `-m "<message>"`. When commit arguments include git flags, gitx passes them through to `git commit`, so commands such as `gitx c --amend` and `gitx c --amend --no-edit` keep normal git behavior.
Commands without a gitx alias pass through to git directly, so `gitx tag`, `gitx branch`, `gitx rebase`, and other git commands work as expected.

### gitx merge manager

`gitx merge` opens an interactive terminal UI for choosing a local or remote branch to merge into the current branch.
The manager shows the current branch, working tree state, recent branch metadata, and a preview of commits that would be brought in.
Use the action row to run a regular merge, `--no-ff`, or `--squash`.
If a merge is already in progress, the same command shows conflicted files, labels the current/ours and incoming/theirs sides of the selected conflict, and exposes the common resolution options directly: keep current, keep incoming, keep both, ask AI to propose a resolved version, open `$EDITOR`, stage, continue, or abort.
AI merge proposals stay inside the TUI for review; approve applies and stages the proposal, edit opens it in `$EDITOR` before approval, and reject returns to the conflict resolver without changing the file.
The AI review screen shows a color-coded diff between the original conflicted file and the AI proposal, with `n` and `p` jumping between changed hunks.
The conflict context is color-coded in the terminal UI so current, incoming, base, both, and editor-oriented options are easy to scan.
Long conflict context is wrapped to at most 80 columns and can be scrolled with `[` and `]`.
Resolver actions show compact shortcut labels such as `o:Ours`, `t:Theirs`, and `i:AI`.
Passing merge arguments keeps normal git behavior, so `gitx merge --abort` and `gitx merge feature` pass through to `git merge`.

### gitx AI commit messages

`gitx c --ai` generates a commit message from staged changes with the OpenAI Responses API, opens a small terminal approval screen, and commits only after approval.
Generated messages use `activity(scope): short info` with a short body for detail.
Before sending the diff to the model, gitx now adds a structured change summary with file counts, line counts, scope candidates, deleted-path highlights, and highest-impact files.
When the staged diff exceeds `ai_max_diff_chars`, gitx keeps a complete changed-file list and uses per-file excerpts so large early assets do not hide later code changes.
Truncated AI prompts also include per-file add/remove counts and preserve deleted lines in excerpts so removal-heavy changes still influence the generated message.
While waiting for OpenAI, the terminal UI shows the current stage of prompt preparation and response generation.

### gitx AI tags

`gitx tag --ai` suggests the next annotated semantic version tag from recent commits since the latest tag.
Before generating the suggestion, the terminal UI shows the latest tag and recent tag history.
The approval screen lets you switch the bump to patch, minor, or major, or edit both the tag name and annotated tag message in your editor before running `git tag -a`.

The default model is `gpt-5.4-mini`. Override it in `~/.config/gitx/config`:

```text
openai_api_key=your_api_key_here
ai_model=gpt-5.4-mini
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
