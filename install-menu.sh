#!/usr/bin/env bash
set -euo pipefail

# Interactive installer launcher for scripts in this repo.
# Uses dialog (or whiptail) checkboxes so you can toggle selections with spacebar.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
  mapfile -t INSTALLERS < <(find "$ROOT_DIR" -mindepth 2 -maxdepth 2 -name install.sh | sort)

  if (( ${#INSTALLERS[@]} == 0 )); then
    echo "No install.sh scripts found."
    exit 1
  fi

  OPTIONS=()
  declare -gA INSTALLER_PATHS=()

  for path in "${INSTALLERS[@]}"; do
    name="$(basename "$(dirname "$path")")"
    OPTIONS+=("$name" "Run ${name}/install.sh" off)
    INSTALLER_PATHS["$name"]="$path"
  done
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
    script_path="${INSTALLER_PATHS[$name]}"
    echo "[*] Running ${name}/install.sh ..."
    (cd "$(dirname "$script_path")" && bash "$(basename "$script_path")")
    echo "[+] Completed ${name}/install.sh"
    echo
  done
}

ensure_ui_tool
collect_installers
prompt_selection
run_installers
