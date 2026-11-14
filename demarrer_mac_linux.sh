#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -r requirements.txt
echo 'Site : http://127.0.0.1:8000'
echo 'API :  http://127.0.0.1:8000/docs'
python -m uvicorn server:app --host 127.0.0.1 --port 8000
