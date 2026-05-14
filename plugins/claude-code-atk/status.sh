#!/bin/bash

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$PLUGIN_DIR/manage.py" status "$PLUGIN_DIR"
