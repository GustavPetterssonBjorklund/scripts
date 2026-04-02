# scripts

Small CLI utilities packaged as a Nix flake.

## Usage

Run a tool directly:

```bash
nix run .#gitx -- -h
nix run .#ovpntmp
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
