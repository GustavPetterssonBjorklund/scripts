#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <folder>"
  exit 1
fi

FOLDER="$(cd "$1" && pwd)"
SHELL_RC="$HOME/.bashrc"

if [[ "${SHELL:-}" == *"zsh" ]] && [[ -f "$HOME/.zshrc" ]]; then
  SHELL_RC="$HOME/.zshrc"
fi

EXPORT_LINE="export PATH=\"$FOLDER:\$PATH\""

if grep -Fqx "$EXPORT_LINE" "$SHELL_RC"; then
  echo "Already in PATH: $FOLDER"
  exit 0
fi

echo "$EXPORT_LINE" >> "$SHELL_RC"
echo "Added to PATH in $SHELL_RC: $FOLDER"
echo "Restart terminal or run: source $SHELL_RC"
