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

Example:

```bash
copy
git rev-parse HEAD | nix run .#copy
cat .env | nix run .#redact
cat incident.log | nix run .#redact -- --yes
```
