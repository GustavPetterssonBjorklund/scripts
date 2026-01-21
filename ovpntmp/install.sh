#!/usr/bin/env bash
set -euo pipefail

RAW_URL="https://raw.githubusercontent.com/GustavPetterssonBjorklund/scripts/main/ovpntmp/ovpntmp.sh"
TARGET="/usr/local/bin/ovpntmp"

echo "[*] Installing prerequisites..."
sudo apt update
sudo apt install -y openvpn curl

echo "[*] Installing ovpntmp helper..."
sudo curl -fsSL "$RAW_URL" -o "$TARGET"
sudo chmod +x "$TARGET"

echo
echo "[+] ovpntmp installed to $TARGET"
echo "[+] Usage: ovpntmp"
