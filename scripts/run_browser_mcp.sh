#!/bin/zsh
# Purpose: Start a pinned, dedicated, loopback browser MCP for supervised capture.
# Inputs: User's manual browser navigation. Outputs: local MCP snapshots.
# Assumptions: Node.js and Google Chrome installed. Author: Carter Tan.
set -eu
cd "$(dirname "$0")/.."
umask 077
command -v npx >/dev/null || { echo "Install Node.js LTS first." >&2; exit 1; }
mkdir -p src/.runtime/browser-mcp-output
# Isolated sessions keep sign-in cookies out of a persistent browser profile.
# The first run downloads the pinned Microsoft package from npm.
cd src/.runtime/browser-mcp-output
exec npx --yes @playwright/mcp@0.0.83 --host 127.0.0.1 --port 8931 --allowed-hosts 127.0.0.1:8931 localhost:8931 --browser chrome --isolated --no-webmcp --block-service-workers --codegen none --output-dir "$PWD"
