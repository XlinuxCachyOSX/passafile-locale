#!/bin/sh
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    exec python3 pasafile.py --open
elif command -v python >/dev/null 2>&1; then
    exec python pasafile.py --open
fi
echo "Python 3 non trovato. Installa Python 3 dal tuo gestore pacchetti."
exit 1
