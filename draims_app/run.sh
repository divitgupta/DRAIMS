#!/bin/bash
# Start DRAIMS on the local network (no internet needed).
# First time:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd "$(dirname "$0")"
export DRAIMS_DB_USER="${DRAIMS_DB_USER:-draims_app}"
if [ -z "$DRAIMS_DB_PASSWORD" ]; then read -r -s -p "MySQL password for $DRAIMS_DB_USER: " DRAIMS_DB_PASSWORD; echo; export DRAIMS_DB_PASSWORD; fi
echo "DRAIMS running at http://localhost:${DRAIMS_PORT:-8000}  (other computers: http://<this-computer-IP>:${DRAIMS_PORT:-8000})"
exec .venv/bin/python app.py
