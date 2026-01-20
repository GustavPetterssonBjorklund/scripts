#!/usr/bin/env bash
set -e

echo "[*] Updating system..."
sudo apt update

echo "[*] Installing prerequisites..."
sudo apt install -y ca-certificates curl gnupg lsb-release

echo "[*] Removing old Docker installations if any..."
sudo apt remove -y docker docker.io containerd runc || true

echo "[*] Adding Docker GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "[*] Adding Docker repository..."
echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

echo "[*] Installing Docker Engine + Compose v2 plugin..."
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[*] Installing legacy docker-compose binary..."
VERSION="1.29.2"
sudo curl -L "https://github.com/docker/compose/releases/download/${VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

echo "[*] Adding current user to docker group..."
sudo usermod -aG docker "$USER"

echo ""
echo "[+] Docker installation complete!"
echo "[+] Versions installed:"
echo "    docker:           $(docker --version || echo 'Not available until re-login')"
echo "    compose (v2):     $(docker compose version || echo 'Pending re-login')"
echo "    docker-compose:   $(docker-compose --version 2>/dev/null || echo 'Pending re-login')"
echo ""
echo "[+] Log out and back in so docker group applies."
echo "[+] Test with:"
echo "    docker run hello-world"
echo "    docker compose version"
echo "    docker-compose --version"
echo ""

