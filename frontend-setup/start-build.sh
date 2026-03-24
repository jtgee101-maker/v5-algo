#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# QUICK START — Run after setup.sh completes
# Opens Claude Code and starts the full build
# ═══════════════════════════════════════════════════════════════

cd "$HOME/ict-trade-desk" || { echo "Run setup.sh first"; exit 1; }

echo ""
echo "🚀 Starting Claude Code build..."
echo ""
echo "Claude will read CLAUDE.md and build everything in phases."
echo "Just say 'yes' to approve each step."
echo ""

# Launch Claude Code with the build instruction
claude -p "Read CLAUDE.md completely. Then execute Phase 1: Create the API layer (all files in src/api/), the Tailwind config with dark terminal theme, and polling hooks. Test by fetching https://v5-algo.onrender.com/api/prices. Show me the result before moving to Phase 2."
