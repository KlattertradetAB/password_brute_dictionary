#!/usr/bin/env bash
# Liten wrapper för gps.py. Skickar vidare alla argument.
# Användning: ./gps.sh            (läs en gång)
#             ./gps.sh --watch    (löpande)
#             ./gps.sh --check    (kontrollera anslutning)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/gps.py" "$@"
