#!/bin/bash
# Setup script for live trading scheduler deployment
# Usage: ./setup.sh [install|uninstall|status|logs]

set -e

SERVICE_NAME="trading-scheduler"
SERVICE_FILE="${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CURRENT_USER="$(whoami)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_requirements() {
    log_info "Checking requirements..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 is not installed"
        exit 1
    fi

    # Check required Python packages
    python3 -c "import schedule, flask, ib_insync, pandas, yaml" 2>/dev/null || {
        log_error "Missing Python packages. Run: pip install -r requirements.txt"
        exit 1
    }

    # Check config exists
    if [ ! -f "$PROJECT_DIR/config/config.yaml" ]; then
        log_error "Config file not found: $PROJECT_DIR/config/config.yaml"
        log_info "Copy config/config.example.yaml to config/config.yaml and update settings"
        exit 1
    fi

    log_info "All requirements satisfied"
}

install_service() {
    check_requirements

    log_info "Installing systemd service..."

    # Create service file with correct user
    TEMP_SERVICE="/tmp/${SERVICE_FILE}"
    sed "s|%i|${CURRENT_USER}|g; s|/home/%i/live-trading-jan2026|${PROJECT_DIR}|g" \
        "$SCRIPT_DIR/$SERVICE_FILE" > "$TEMP_SERVICE"

    # Copy to systemd directory
    sudo cp "$TEMP_SERVICE" "/etc/systemd/system/${SERVICE_NAME}@${CURRENT_USER}.service"
    rm "$TEMP_SERVICE"

    # Create required directories
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/data/snapshots"
    mkdir -p "$PROJECT_DIR/data/executions"
    mkdir -p "$PROJECT_DIR/data/annotations"
    mkdir -p "$PROJECT_DIR/reports/monthly"

    # Reload systemd
    sudo systemctl daemon-reload

    log_info "Service installed successfully"
    log_info ""
    log_info "To start the service:"
    log_info "  sudo systemctl start ${SERVICE_NAME}@${CURRENT_USER}"
    log_info ""
    log_info "To enable on boot:"
    log_info "  sudo systemctl enable ${SERVICE_NAME}@${CURRENT_USER}"
    log_info ""
    log_info "To check status:"
    log_info "  sudo systemctl status ${SERVICE_NAME}@${CURRENT_USER}"
}

uninstall_service() {
    log_info "Uninstalling systemd service..."

    # Stop and disable service
    sudo systemctl stop "${SERVICE_NAME}@${CURRENT_USER}" 2>/dev/null || true
    sudo systemctl disable "${SERVICE_NAME}@${CURRENT_USER}" 2>/dev/null || true

    # Remove service file
    sudo rm -f "/etc/systemd/system/${SERVICE_NAME}@${CURRENT_USER}.service"

    # Reload systemd
    sudo systemctl daemon-reload

    log_info "Service uninstalled successfully"
}

show_status() {
    log_info "Service status:"
    sudo systemctl status "${SERVICE_NAME}@${CURRENT_USER}" --no-pager || true

    echo ""
    log_info "Health check:"
    curl -s http://127.0.0.1:8080/health && echo " - OK" || echo "Not responding"

    echo ""
    log_info "Scheduler status:"
    curl -s http://127.0.0.1:8080/status | python3 -m json.tool 2>/dev/null || echo "Not available"
}

show_logs() {
    log_info "Recent scheduler logs:"
    tail -50 "$PROJECT_DIR/logs/scheduler.log" 2>/dev/null || log_warn "No logs found"
}

test_connection() {
    log_info "Testing IBKR connection..."
    cd "$PROJECT_DIR"
    python3 -c "
from src.execution_logger import IBKRConnection, load_config
config = load_config()
conn = IBKRConnection(config)
if conn.connect(max_retries=1):
    print('Connection successful!')
    conn.disconnect()
else:
    print('Connection failed!')
    exit(1)
"
}

run_manual() {
    log_info "Running scheduler in foreground (Ctrl+C to stop)..."
    cd "$PROJECT_DIR"
    python3 main.py scheduler
}

show_help() {
    echo "Live Trading Scheduler Setup"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  install     Install systemd service"
    echo "  uninstall   Uninstall systemd service"
    echo "  status      Show service and scheduler status"
    echo "  logs        Show recent scheduler logs"
    echo "  test        Test IBKR connection"
    echo "  run         Run scheduler in foreground"
    echo "  help        Show this help message"
}

# Main
case "${1:-help}" in
    install)
        install_service
        ;;
    uninstall)
        uninstall_service
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    test)
        test_connection
        ;;
    run)
        run_manual
        ;;
    help|*)
        show_help
        ;;
esac
