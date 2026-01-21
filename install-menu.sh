#!/usr/bin/env bash
set -euo pipefail

# Interactive installer launcher for scripts in this repo.
# Uses dialog (or whiptail) checkboxes so you can toggle selections with spacebar.

if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  RUN_MODE="local"
else
  # Running via curl | bash; operate in a temp dir and pull installers from GitHub.
  ROOT_DIR="$(mktemp -d)"
  RUN_MODE="remote"
fi

# Remote installers to offer when not running from a checkout.
# Format: name=url
REMOTE_INSTALLERS=(
  "docker=https://raw.githubusercontent.com/GustavPetterssonBjorklund/scripts/main/docker/install.sh"
  "ovpntmp=https://raw.githubusercontent.com/GustavPetterssonBjorklund/scripts/main/ovpntmp/install.sh"
)

ensure_ui_tool() {
  if command -v dialog >/dev/null 2>&1; then
    UI_TOOL="dialog"
    return
  fi

  if command -v whiptail >/dev/null 2>&1; then
    UI_TOOL="whiptail"
    return
  fi

  echo "[*] Installing dialog for interactive checklist..."
  sudo apt update
  sudo apt install -y dialog
  UI_TOOL="dialog"
}

collect_installers() {
  OPTIONS=()
  declare -gA INSTALLER_PATHS=()

  if [[ "$RUN_MODE" == "local" ]]; then
    mapfile -t INSTALLERS < <(find "$ROOT_DIR" -mindepth 2 -maxdepth 2 -name install.sh | sort)

    if (( ${#INSTALLERS[@]} == 0 )); then
      echo "No install.sh scripts found."
      exit 1
    fi

    for path in "${INSTALLERS[@]}"; do
      name="$(basename "$(dirname "$path")")"
      OPTIONS+=("$name" "Run ${name}/install.sh" off)
      INSTALLER_PATHS["$name"]="$path"
    done
  else
    for entry in "${REMOTE_INSTALLERS[@]}"; do
      name="${entry%%=*}"
      url="${entry#*=}"
      local_path="$ROOT_DIR/${name}-install.sh"
      OPTIONS+=("$name" "Run ${name}/install.sh" off)
      INSTALLER_PATHS["$name"]="$local_path|$url"
    done
  fi
}

prompt_selection() {
  if [[ "$UI_TOOL" == "dialog" ]]; then
    choices=$(dialog --stdout --separate-output \
      --checklist "Select installers to run (spacebar to toggle)" \
      20 70 10 \
      "${OPTIONS[@]}")
  else
    choices=$(whiptail --separate-output --checklist \
      "Select installers to run (spacebar to toggle)" \
      20 70 10 \
      "${OPTIONS[@]}" 3>&1 1>&2 2>&3)
  fi

  clear

  if [[ -z "$choices" ]]; then
    echo "No installers selected."
    exit 0
  fi

  SELECTED=()
  while read -r choice; do
    [[ -n "$choice" ]] && SELECTED+=("$choice")
  done <<< "$choices"
}

run_installers() {
  for name in "${SELECTED[@]}"; do
    entry="${INSTALLER_PATHS[$name]}"

    if [[ "$RUN_MODE" == "remote" ]]; then
      # entry format: local_path|url
      script_path="${entry%%|*}"
      url="${entry#*|}"
      echo "[*] Downloading ${name}/install.sh ..."
      curl -fsSL "$url" -o "$script_path"
      chmod +x "$script_path"
      echo "[*] Running ${name}/install.sh ..."
      bash "$script_path"
    else
      script_path="$entry"
      echo "[*] Running ${name}/install.sh ..."
      (cd "$(dirname "$script_path")" && bash "$(basename "$script_path")")
    fi

    echo "[+] Completed ${name}/install.sh"
    echo
  done
}

ensure_ui_tool
collect_installers
prompt_selection
run_installers
