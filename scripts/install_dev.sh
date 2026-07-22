#!/usr/bin/env bash
set -euo pipefail

export APP_ENV="${APP_ENV:-dev}"
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" "$@"
