#!/bin/bash
# ============================================================
# ONE-COMMAND VPS BOOTSTRAP
# ============================================================
# After creating your Oracle Cloud VM and SSH'ing in, run:
#
#   curl -sSL https://raw.githubusercontent.com/amr-coding1/live-trading-jan2026/main/deploy/bootstrap.sh | bash
#
# Or if you've cloned the repo already:
#   bash deploy/bootstrap.sh
#
# This script does everything: installs Docker, clones the repo,
# prompts for credentials, builds containers, and starts trading.
# ============================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
ask()  { echo -e "${BLUE}[?]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo "============================================"
echo "  Live Trading System - VPS Bootstrap"
echo "============================================"
echo ""

# ── Step 1: Install Docker ───────────────────────────────────
if command -v docker &> /dev/null; then
    log "Docker already installed: $(docker --version)"
else
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    warn "Docker installed. If 'docker compose' fails later, log out and back in first."
fi

# Ensure docker compose is available
if ! docker compose version &> /dev/null 2>&1; then
    sudo apt-get install -y docker-compose-plugin 2>/dev/null || true
fi

# ── Step 2: Clone repo ──────────────────────────────────────
PROJECT_DIR="$HOME/live-trading-jan2026"

if [ -d "$PROJECT_DIR" ]; then
    log "Repo already exists at $PROJECT_DIR"
    cd "$PROJECT_DIR"
    git pull origin main || true
else
    log "Cloning repository..."
    sudo apt-get update -qq && sudo apt-get install -y -qq git > /dev/null
    git clone https://github.com/amr-coding1/live-trading-jan2026.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# ── Step 3: Collect credentials ──────────────────────────────
echo ""
echo "────────────────────────────────────────────"
echo "  Configure IBKR & Email credentials"
echo "────────────────────────────────────────────"
echo ""

if [ -f .env ]; then
    warn ".env file already exists. Skipping credential setup."
    warn "Edit manually with: nano $PROJECT_DIR/.env"
else
    ask "Enter your IBKR username: "
    read -r IB_USER
    ask "Enter your IBKR password: "
    read -rs IB_PASS
    echo ""

    ask "Trading mode - paper or live? [paper]: "
    read -r TRADE_MODE
    TRADE_MODE=${TRADE_MODE:-paper}

    cat > .env << ENVEOF
# IB Gateway credentials
IB_USERNAME=${IB_USER}
IB_PASSWORD=${IB_PASS}
IB_TRADING_MODE=${TRADE_MODE}
VNC_PASSWORD=trader$(date +%s | tail -c 5)
ENVEOF

    log "Created .env file"
fi

# ── Step 4: Set up config ────────────────────────────────────
if [ ! -f config/config.yaml ]; then
    cp config/config.docker.yaml config/config.yaml
    log "Created config/config.yaml from Docker template"
    warn "Email notifications disabled by default."
    warn "Edit config/config.yaml to enable them."
else
    log "config/config.yaml already exists"
fi

# Set execution mode to dry_run for safety
if grep -q 'mode: "live"' config/config.yaml; then
    sed -i 's/mode: "live"/mode: "dry_run"/' config/config.yaml
    warn "Set execution mode to dry_run for safety. Change to 'live' when ready."
fi

# ── Step 5: Configure firewall ───────────────────────────────
log "Configuring firewall..."
sudo apt-get install -y -qq ufw > /dev/null 2>&1 || true
sudo ufw default deny incoming > /dev/null 2>&1 || true
sudo ufw default allow outgoing > /dev/null 2>&1 || true
sudo ufw allow ssh > /dev/null 2>&1 || true
sudo ufw allow 5050/tcp > /dev/null 2>&1 || true  # Dashboard
sudo ufw allow 8080/tcp > /dev/null 2>&1 || true  # Health check
sudo ufw --force enable > /dev/null 2>&1 || true
log "Firewall configured (SSH + Dashboard + Health)"

# ── Step 6: Create data directories ─────────────────────────
mkdir -p data/executions data/snapshots data/signals data/annotations/monthly
mkdir -p reports/monthly logs
log "Data directories created"

# ── Step 7: Build and start ──────────────────────────────────
echo ""
log "Building Docker containers (this may take 2-3 minutes)..."
sudo docker compose build

echo ""
log "Starting services..."
sudo docker compose up -d

# ── Step 8: Wait and verify ──────────────────────────────────
echo ""
log "Waiting for services to start..."
sleep 10

echo ""
echo "============================================"
echo "  SERVICE STATUS"
echo "============================================"
sudo docker compose ps
echo ""

# Check if scheduler is responding
for i in {1..6}; do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        log "Scheduler health check: OK"
        break
    fi
    if [ "$i" -eq 6 ]; then
        warn "Scheduler not responding yet. It may still be starting."
        warn "Check logs: sudo docker compose logs -f trading-scheduler"
    else
        echo "  Waiting for scheduler... (${i}/6)"
        sleep 10
    fi
done

echo ""
echo "============================================"
echo "  SETUP COMPLETE!"
echo "============================================"
echo ""
log "Dashboard:  http://$(curl -sf ifconfig.me 2>/dev/null || echo '<your-ip>'):5050"
log "Health:     http://$(curl -sf ifconfig.me 2>/dev/null || echo '<your-ip>'):8080/health"
echo ""
log "Useful commands:"
echo "  sudo docker compose logs -f            # Watch all logs"
echo "  sudo docker compose logs -f ib-gateway # IB Gateway logs"
echo "  sudo docker compose ps                 # Service status"
echo "  sudo docker compose restart             # Restart everything"
echo "  sudo docker compose down                # Stop everything"
echo ""
warn "Execution mode is DRY RUN. When ready for live:"
echo "  1. nano config/config.yaml"
echo "  2. Change mode: \"dry_run\" → mode: \"live\""
echo "  3. sudo docker compose restart trading-scheduler"
echo ""
