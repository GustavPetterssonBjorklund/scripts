#!/usr/bin/env bash
set -e

echo "[*] Detecting distribution..."
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
else
  echo "[!] Cannot read /etc/os-release, aborting."
  exit 1
fi

echo "[*] Updating system..."
sudo apt update

echo "[*] Installing prerequisites..."
sudo apt install -y ca-certificates curl gnupg lsb-release

echo "[*] Removing old Docker installations if any..."
sudo apt remove -y docker docker.io containerd runc || true

if [[ "$ID" == "kali" ]]; then
  echo "[*] Detected Kali Linux (ID=$ID, VERSION_CODENAME=${VERSION_CODENAME:-unknown})"
  echo "[*] Using Kali's own docker.io + docker-compose packages."

  # Clean up any previous Docker.com repo file if it exists
  if [[ -f /etc/apt/sources.list.d/docker.list ]]; then
    echo "[*] Removing existing /etc/apt/sources.list.d/docker.list (Docker.com repo not valid for Kali)..."
    sudo rm /etc/apt/sources.list.d/docker.list
  fi

  echo "[*] Updating apt after cleanup..."
  sudo apt update

  echo "[*] Installing docker.io + docker-compose from Kali repos..."
  sudo apt install -y docker.io docker-compose

else
  echo "[*] Detected non-Kali Debian-based system (ID=$ID, VERSION_CODENAME=${VERSION_CODENAME:-unknown})"
  echo "[*] Using Docker's official repository."

  echo "[*] Adding Docker GPG key..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
  sudo chmod a+r /etc/apt/keyrings/docker.asc

  echo "[*] Adding Docker repository..."
  echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian \
${VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  echo "[*] Installing Docker Engine + Compose v2 plugin..."
  sudo apt update
  sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  echo "[*] Installing legacy docker-compose binary..."
  VERSION="1.29.2"
  sudo curl -L "https://github.com/docker/compose/releases/download/${VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
fi

echo "[*] Adding current user to docker group..."
sudo usermod -aG docker "$USER"

echo ""
echo "[+] Docker installation complete!"
echo "[+] Versions (some may need re-login to show correctly):"
echo "    docker:           $(docker --version 2>/dev/null || echo 'Not available until re-login')"

# v2 compose (plugin) – only guaranteed on non-Kali branch,
# but safe to try everywhere:
echo "    compose (v2):     $(docker compose version 2>/dev/null || echo 'Unavailable or pending re-login')"

# legacy docker-compose – present on non-Kali via binary, on Kali via package:
echo "    docker-compose:   $(docker-compose --version 2>/dev/null || echo 'Unavailable or pending re-login')"

echo ""
echo "[+] Log out and back in (or run: exec su - $USER) so docker group applies."
echo "[+] Test with:"
echo "    docker run hello-world"
echo "    docker compose version   # if available"
echo "    docker-compose --version # if installed"
echo ""
