#!/bin/bash
# ============================================================
# VPS Deployment Script for Live Trading Scheduler
# ============================================================
# Usage: ./vps-setup.sh [install|start|stop|status|logs|update]
#
# Prerequisites:
#   - Ubuntu 22.04+ VPS (DigitalOcean, Hetzner, AWS, etc.)
#   - SSH access with sudo privileges
#   - .env file configured with IB credentials
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC}  $1"; }

# ── Install Docker and dependencies ─────────────────────────
install_docker() {
    log_step "Installing Docker..."

    if command -v docker &> /dev/null; then
        log_info "Docker already installed: $(docker --version)"
    else
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        log_info "Docker installed. You may need to log out and back in."
    fi

    if command -v docker compose &> /dev/null; then
        log_info "Docker Compose already available"
    else
        sudo apt-get install -y docker-compose-plugin
        log_info "Docker Compose installed"
    fi
}

# ── Full VPS setup ───────────────────────────────────────────
install() {
    log_step "Setting up VPS for live trading..."

    # Install Docker
    install_docker

    # Install monitoring tools
    sudo apt-get update && sudo apt-get install -y \
        htop \
        curl \
        jq \
        fail2ban \
        ufw

    # Configure firewall
    log_step "Configuring firewall..."
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow ssh
    sudo ufw allow 5050/tcp   # Dashboard
    sudo ufw allow 8080/tcp   # Health check
    sudo ufw --force enable

    # Check .env file
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        log_warn ".env file not found. Creating from template..."
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        log_error "Edit .env with your IB credentials before starting:"
        log_error "  nano $PROJECT_DIR/.env"
        return 1
    fi

    # Build containers
    log_step "Building Docker containers..."
    cd "$PROJECT_DIR"
    docker compose build

    log_info "Installation complete!"
    log_info ""
    log_info "Next steps:"
    log_info "  1. Edit .env with your IB credentials"
    log_info "  2. Edit config/config.docker.yaml (or copy to config/config.yaml)"
    log_info "  3. Run: ./deploy/vps-setup.sh start"
}

# ── Start all services ───────────────────────────────────────
start() {
    log_step "Starting trading services..."
    cd "$PROJECT_DIR"

    if [ ! -f ".env" ]; then
        log_error ".env file required. Run: ./deploy/vps-setup.sh install"
        exit 1
    fi

    docker compose up -d
    log_info "Services starting... (IB Gateway may take 2-3 minutes)"
    log_info ""
    log_info "Monitor startup:"
    log_info "  docker compose logs -f ib-gateway"
    log_info ""
    log_info "Check health:"
    log_info "  ./deploy/vps-setup.sh status"
}

# ── Stop all services ────────────────────────────────────────
stop() {
    log_step "Stopping trading services..."
    cd "$PROJECT_DIR"
    docker compose down
    log_info "All services stopped"
}

# ── Show status ──────────────────────────────────────────────
status() {
    log_step "Service status:"
    cd "$PROJECT_DIR"
    docker compose ps
    echo ""

    log_step "Health checks:"
    echo -n "  Scheduler: "
    curl -sf http://localhost:8080/health && echo " OK" || echo "NOT RESPONDING"

    echo -n "  Dashboard: "
    curl -sf http://localhost:5050/ > /dev/null && echo " OK" || echo "NOT RESPONDING"

    echo ""
    log_step "Scheduler status:"
    curl -sf http://localhost:8080/status | jq '.' 2>/dev/null || echo "  Not available"
}

# ── Show logs ────────────────────────────────────────────────
logs() {
    cd "$PROJECT_DIR"
    local service="${1:-trading-scheduler}"
    docker compose logs -f --tail=100 "$service"
}

# ── Update code and restart ──────────────────────────────────
update() {
    log_step "Updating trading system..."
    cd "$PROJECT_DIR"

    git pull origin main

    docker compose build trading-scheduler dashboard
    docker compose up -d trading-scheduler dashboard

    log_info "Updated and restarted"
}

# ── Monitor (continuous health check) ────────────────────────
monitor() {
    log_step "Starting continuous monitoring (Ctrl+C to stop)..."
    while true; do
        clear
        echo "=== Trading System Monitor === $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
        echo ""
        status 2>/dev/null || true
        echo ""
        echo "--- Recent scheduler log ---"
        docker compose logs --tail=10 trading-scheduler 2>/dev/null || true
        sleep 30
    done
}

# ── Main ─────────────────────────────────────────────────────
show_help() {
    echo "VPS Deployment for Live Trading Scheduler"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  install   Install Docker, build containers, configure firewall"
    echo "  start     Start all trading services"
    echo "  stop      Stop all trading services"
    echo "  status    Show service health and scheduler status"
    echo "  logs      Follow service logs (default: trading-scheduler)"
    echo "  update    Pull latest code and restart"
    echo "  monitor   Continuous health monitoring dashboard"
    echo "  help      Show this help"
}

case "${1:-help}" in
    install)  install ;;
    start)    start ;;
    stop)     stop ;;
    status)   status ;;
    logs)     logs "${2:-trading-scheduler}" ;;
    update)   update ;;
    monitor)  monitor ;;
    help|*)   show_help ;;
esac
