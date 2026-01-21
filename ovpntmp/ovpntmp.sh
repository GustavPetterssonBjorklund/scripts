#!/usr/bin/env bash

set -euo pipefail

OVPN_DIR="$HOME/Downloads"

# Colors
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
RESET="\033[0m"

# Status wrappers
ok()      { echo -e "${GREEN}✔ OK${RESET} $*"; }
info()    { echo -e "${YELLOW}ℹ${RESET}  $*"; }
run()     { echo -e "${BLUE}▶ RUNNING${RESET} $*"; }
fail()    { echo -e "${RED}✖ FAILED${RESET} $*"; }

# Collect .ovpn files
mapfile -t OVPN_FILES < <(find "$OVPN_DIR" -maxdepth 1 -type f -name '*.ovpn' | sort)

if (( ${#OVPN_FILES[@]} == 0 )); then
  fail "No .ovpn files found in $OVPN_DIR"
  exit 1
fi

chosen_file=""

if (( ${#OVPN_FILES[@]} == 1 )); then
  chosen_file="${OVPN_FILES[0]}"
  info "Found single .ovpn:"
  echo "    $chosen_file"
else
  info "Multiple .ovpn files found:"
  for i in "${!OVPN_FILES[@]}"; do
    printf "  %2d) %s\n" "$((i+1))" "${OVPN_FILES[$i]}"
  done
  echo

  while :; do
    read -rp "Select file (1-${#OVPN_FILES[@]}): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#OVPN_FILES[@]} )); then
      idx=$((choice-1))
      chosen_file="${OVPN_FILES[$idx]}"
      break
    else
      info "Invalid choice, try again."
    fi
  done

  echo
  ok "Selected:"
  echo "    $chosen_file"
  echo

  read -rp "Delete all other .ovpn files? [y/N]: " ans
  ans=${ans:-n}

  if [[ "$ans" =~ ^[Yy]$ ]]; then
    info "Cleaning up..."
    for i in "${!OVPN_FILES[@]}"; do
      if (( i != idx )); then
        rm -- "${OVPN_FILES[$i]}" && ok "Removed $(basename "${OVPN_FILES[$i]}")"
      fi
    done
  else
    info "Keeping other .ovpn files."
  fi
fi

echo
run "Starting OpenVPN:"
echo "    $chosen_file"
echo

# Run OpenVPN
if sudo openvpn --config "$chosen_file"; then
  echo
  ok "OpenVPN exited cleanly."
else
  code=$?
  echo
  fail "OpenVPN exited with code $code."
  exit $code
fi


