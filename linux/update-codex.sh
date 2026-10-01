#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# steps.sh selects the same fnm/Node environment as the installation wizard.
exec bash "$ROOT/steps.sh" apply codex
