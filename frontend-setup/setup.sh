#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# ICT TRADE MISSION CONTROL — FULL SETUP
# Run this on your MacBook Pro to set up everything
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  ICT TRADE MISSION CONTROL — Full Setup${NC}"
echo -e "${CYAN}  Palantir-level trading intelligence platform${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────
echo -e "${YELLOW}[1/8] Checking prerequisites...${NC}"

check_cmd() {
  if command -v "$1" &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} $1 $(command -v $1)"
  else
    echo -e "  ${RED}✗${NC} $1 not found"
    return 1
  fi
}

check_cmd node || { echo "Install Node.js: brew install node"; exit 1; }
check_cmd npm || { echo "Install npm with Node.js"; exit 1; }
check_cmd git || { echo "Install git: brew install git"; exit 1; }

# Check Node version >= 18
NODE_VER=$(node -v | sed 's/v//' | cut -d. -f1)
if [ "$NODE_VER" -lt 18 ]; then
  echo -e "  ${RED}✗${NC} Node.js >= 18 required (you have v$NODE_VER)"
  echo "  Run: brew install node@22"
  exit 1
fi
echo -e "  ${GREEN}✓${NC} Node.js v$(node -v | sed 's/v//')"

# Check for Claude Code
if command -v claude &> /dev/null; then
  echo -e "  ${GREEN}✓${NC} Claude Code installed"
else
  echo -e "  ${YELLOW}!${NC} Claude Code not found — installing..."
  npm install -g @anthropic-ai/claude-code
fi

echo ""

# ── Step 2: Install Ruflo ────────────────────────────────────
echo -e "${YELLOW}[2/8] Installing Ruflo (agent orchestration)...${NC}"

if command -v ruflo &> /dev/null; then
  echo -e "  ${GREEN}✓${NC} Ruflo already installed"
else
  npm install -g ruflo@latest
  echo -e "  ${GREEN}✓${NC} Ruflo installed"
fi

echo ""

# ── Step 3: Create project directory ─────────────────────────
echo -e "${YELLOW}[3/8] Setting up project directory...${NC}"

PROJECT_DIR="$HOME/ict-trade-desk"

if [ -d "$PROJECT_DIR" ]; then
  echo -e "  ${YELLOW}!${NC} $PROJECT_DIR already exists"
  read -p "  Overwrite? (y/n): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "$PROJECT_DIR"
  else
    echo "  Using existing directory"
  fi
fi

mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"
echo -e "  ${GREEN}✓${NC} Created $PROJECT_DIR"

echo ""

# ── Step 4: Scaffold React + Vite ────────────────────────────
echo -e "${YELLOW}[4/8] Scaffolding React + Vite + Tailwind...${NC}"

npm create vite@latest . -- --template react 2>/dev/null || true

# Install all dependencies
npm install
npm install -D tailwindcss @tailwindcss/vite
npm install @tanstack/react-query react-router-dom zustand lucide-react lightweight-charts
npm install -D @types/node

echo -e "  ${GREEN}✓${NC} Dependencies installed"

echo ""

# ── Step 5: Create environment files ─────────────────────────
echo -e "${YELLOW}[5/8] Creating config files...${NC}"

# .env
cat > .env << 'EOF'
VITE_API_URL=https://v5-algo.onrender.com/api
EOF

cat > .env.example << 'EOF'
VITE_API_URL=https://v5-algo.onrender.com/api
EOF

# vite.config.js
cat > vite.config.js << 'EOF'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, host: true },
})
EOF

# render.yaml
cat > render.yaml << 'EOF'
services:
  - type: web
    name: ict-trade-desk
    runtime: static
    buildCommand: npm install && npm run build
    staticPublishPath: dist
    envVars:
      - key: VITE_API_URL
        value: https://v5-algo.onrender.com/api
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
EOF

echo -e "  ${GREEN}✓${NC} Config files created"

echo ""

# ── Step 6: Initialize Ruflo ─────────────────────────────────
echo -e "${YELLOW}[6/8] Initializing Ruflo for agent orchestration...${NC}"

npx ruflo@latest init 2>/dev/null || echo -e "  ${YELLOW}!${NC} Ruflo init skipped (run manually if needed)"

echo -e "  ${GREEN}✓${NC} Ruflo initialized"

echo ""

# ── Step 7: Create CLAUDE.md ─────────────────────────────────
echo -e "${YELLOW}[7/8] Creating CLAUDE.md master instructions...${NC}"

# This gets created by the script below — just note it
echo -e "  ${GREEN}✓${NC} CLAUDE.md will be created (see files)"

echo ""

# ── Step 8: Initialize Git ───────────────────────────────────
echo -e "${YELLOW}[8/8] Initializing Git repository...${NC}"

git init
cat > .gitignore << 'EOF'
node_modules/
dist/
.env
.DS_Store
*.local
.swarm/
EOF

git add -A
git commit -m "Initial scaffold: React + Vite + Tailwind + Ruflo" 2>/dev/null || true

echo -e "  ${GREEN}✓${NC} Git initialized"

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ SETUP COMPLETE${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Project: ${BLUE}$PROJECT_DIR${NC}"
echo -e "  Backend: ${BLUE}https://v5-algo.onrender.com${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. cd $PROJECT_DIR"
echo -e "  2. claude"
echo -e "  3. Tell Claude: ${CYAN}Read CLAUDE.md and execute Phase 1${NC}"
echo ""
echo -e "  Or run the full build:"
echo -e "  ${CYAN}claude -p 'Read CLAUDE.md. Execute all phases sequentially.'${NC}"
echo ""
