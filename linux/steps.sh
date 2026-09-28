#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:?check or apply}"; ITEM="${2:?step}"
export BOOTSTRAP_STEP="$ITEM"
[[ "$MODE" = check || "$MODE" = apply ]] || exit 2
export PATH="$HOME/.local/bin:$HOME/.local/share/fnm:$PATH"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
if command -v fnm >/dev/null 2>&1; then eval "$(fnm env --shell bash)"; fi
NODE_VERSION=22.23.2
packages=(build-essential ca-certificates curl git unzip python3)
apt_install() {
  sudo apt-get update -qq
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}
shell_config() { python3 "$ROOT/settings.py" shell; }
has_packages() { local p; for p in "$@"; do dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -qx 'install ok installed' || return 1; done; }
check() {
  case "$ITEM" in
    base) has_packages "${packages[@]}" && python3 "$ROOT/settings.py" check-shell ;;
    node) [[ "$(node -v 2>/dev/null)" = "v$NODE_VERSION" ]] && corepack yarn --version >/dev/null && python3 "$ROOT/settings.py" check-shell ;;
    gh) gh --version >/dev/null 2>&1 && test -s /etc/apt/sources.list.d/github-cli.list ;;
    claude|codex) "$ITEM" --version >/dev/null 2>&1 ;;
    zsh) [[ "$(getent passwd "$(id -un)" | cut -d: -f7)" = /usr/bin/zsh ]] && python3 "$ROOT/settings.py" check-shell ;;
    shell-theme) test -d "$HOME/.zsh/zsh-autosuggestions" && test -d "$HOME/.zsh/zsh-syntax-highlighting" && python3 "$ROOT/settings.py" check-theme ;;
    shell-replace) python3 "$ROOT/settings.py" check-replace ;;
    git-name) [[ "$(git config --global user.name || true)" = "$GIT_USER_NAME" ]] ;;
    git-email) [[ "$(git config --global user.email || true)" = "$GIT_USER_EMAIL" ]] ;;
    git-branch) [[ "$(git config --global init.defaultBranch || true)" = main ]] ;;
    git-gcm) python3 "$ROOT/settings.py" check-gcm ;;
    timezone) [[ "$(cat /etc/timezone 2>/dev/null || true)" = "$TIMEZONE" ]] && [[ "$(readlink -f /etc/localtime)" = "$(readlink -f "/usr/share/zoneinfo/$TIMEZONE")" ]] ;;
    claude-settings|claude-permissions|claude-skill|claude-commands|codex-skills) python3 "$ROOT/settings.py" "check-$ITEM" ;;
    kb)
      test -d "$MURING_KB_DIR/.git"
      origin="$(git -C "$MURING_KB_DIR" remote get-url origin)"
      [[ "$origin" = "$MURING_KB_REPO" || "$MURING_KB_REPO|$origin" = 'https://github.com/Muring/muring-kb.git|git@github.com:Muring/muring-kb.git' ]]
      test -f "$MURING_KB_DIR/scripts/setup.py"
      python3 "$MURING_KB_DIR/scripts/setup.py" --client all --check
      test "$HOME/.local/bin/mkb" -ef "$MURING_KB_DIR/scripts/kb.py"
      "$HOME/.local/bin/mkb" --version ;;
    orca)
      for skill in computer-use orca-cli orchestration; do
        [[ -f "$HOME/.agents/skills/$skill/SKILL.md" || -f "$HOME/.claude/skills/$skill/SKILL.md" ]] || return 20
      done ;;
    orca-auto) powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/install-orca-auto.ps1")" -Check >/dev/null ;;
    orca-monitor) powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/install-orca-wsl-monitor.ps1")" -Check >/dev/null ;;
    orca-patch) powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/check-orca.ps1")" -Patched >/dev/null ;;
    *) return 2 ;;
  esac
}
apply() {
  case "$ITEM" in
    base) apt_install "${packages[@]}"; shell_config ;;
    node)
      if [[ ! -x "$HOME/.local/share/fnm/fnm" ]]; then curl -fsSL https://fnm.vercel.app/install | bash -s -- --install-dir "$HOME/.local/share/fnm" --skip-shell; fi
      eval "$(fnm env --shell bash)"
      fnm install "$NODE_VERSION"; fnm default "$NODE_VERSION"; fnm use "$NODE_VERSION"
      corepack enable; shell_config ;;
    gh)
      sudo mkdir -p -m 755 /etc/apt/keyrings
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
      sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
      printf 'deb [arch=%s signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\n' "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
      apt_install gh ;;
    claude) npm install -g @anthropic-ai/claude-code ;;
    codex) npm install -g @openai/codex ;;
    zsh) apt_install zsh; sudo chsh -s /usr/bin/zsh "$(id -un)"; shell_config ;;
    shell-theme)
      mkdir -p "$HOME/.zsh"
      for plugin in zsh-autosuggestions zsh-syntax-highlighting; do
        if [[ ! -d "$HOME/.zsh/$plugin" ]]; then git clone --depth=1 "https://github.com/zsh-users/$plugin.git" "$HOME/.zsh/$plugin"; fi
      done
      shell_config ;;
    shell-replace) python3 "$ROOT/settings.py" replace ;;
    git-name|git-email|git-branch|git-gcm|claude-settings|claude-permissions|claude-skill|claude-commands|codex-skills) python3 "$ROOT/settings.py" "$ITEM" ;;
    timezone)
      test -f "/usr/share/zoneinfo/$TIMEZONE"
      sudo ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
      printf '%s\n' "$TIMEZONE" | sudo tee /etc/timezone >/dev/null ;;
    kb) timeout --foreground 300s bash "$ROOT/setup-kb.sh" || return 20 ;;
    orca)
      command -v orca-ide >/dev/null 2>&1 || return 20
      timeout --foreground 120s orca-ide skills install --skill computer-use --skill orca-cli --skill orchestration || true
      check ;;
    orca-auto) timeout --foreground 120s powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/install-orca-auto.ps1")" ;;
    orca-monitor) timeout --foreground 120s powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/install-orca-wsl-monitor.ps1")" ;;
    orca-patch) timeout --foreground 180s powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/../windows/fix-orca-wsl-rename.ps1")" ;;
    *) return 2 ;;
  esac
}
"$MODE"
