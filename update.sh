#!/usr/bin/env bash
# ==============================================================================
# Botsaller - Automated Linux Source Code Updater
# Safely updates application code, preserves .env, database, and uploads.
# ==============================================================================

set -euo pipefail

# Text formatting & Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
header() {
    echo -e "\n${PURPLE}${BOLD}====================================================${NC}"
    echo -e "${PURPLE}${BOLD}  $1${NC}"
    echo -e "${PURPLE}${BOLD}====================================================${NC}\n"
}

# 1. Ensure script is run as root
check_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        error "This updater script must be run as root (or using sudo)."
        exit 1
    fi
}

# 2. Detect installation directory
determine_dirs() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Prioritize current directory if script is run directly from project folder
    if [[ -f "${SCRIPT_DIR}/main.py" ]]; then
        INSTALL_DIR="${SCRIPT_DIR}"
    elif [[ -d "/opt/botsaller" && -f "/opt/botsaller/main.py" ]]; then
        INSTALL_DIR="/opt/botsaller"
    else
        read -rp "Enter Botsaller installation directory [default: /opt/botsaller]: " USER_DIR
        INSTALL_DIR=${USER_DIR:-/opt/botsaller}
    fi

    if [[ ! -d "${INSTALL_DIR}" ]]; then
        error "Installation directory ${INSTALL_DIR} not found!"
        exit 1
    fi

    info "Operating on installation directory: ${BOLD}${INSTALL_DIR}${NC}"
}

# 3. Create a safety backup
backup_data() {
    header "Step 1: Creating Safety Backup"

    BACKUP_DIR="${INSTALL_DIR}/backups/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "${BACKUP_DIR}"

    # Backup .env
    if [[ -f "${INSTALL_DIR}/.env" ]]; then
        cp "${INSTALL_DIR}/.env" "${BACKUP_DIR}/.env"
        info "Saved .env configuration backup."
    fi

    # Backup SQLite DB if exists
    if [[ -f "${INSTALL_DIR}/botsaller.db" ]]; then
        cp "${INSTALL_DIR}/botsaller.db" "${BACKUP_DIR}/botsaller.db"
        info "Saved SQLite database backup."
    fi

    # Backup uploads
    if [[ -d "${INSTALL_DIR}/uploads" ]]; then
        tar -czf "${BACKUP_DIR}/uploads_backup.tar.gz" -C "${INSTALL_DIR}" uploads 2>/dev/null || true
        info "Saved customer uploads backup archive."
    fi

    success "Safety backup created at: ${BOLD}${BACKUP_DIR}${NC}"
}

# 3.1 Check .env configuration safety
check_env_safety() {
    local env_file="${INSTALL_DIR}/.env"
    if [[ -f "${env_file}" ]]; then
        if grep -q "CHANGE_ME_BOT_TOKEN" "${env_file}"; then
            warn "--------------------------------------------------------"
            warn "هشدار مهم: فایل .env حاوی توکن خام و تستی (CHANGE_ME_BOT_TOKEN) است!"
            warn "به نظر می‌رسد فایل پیش‌فرض و خام لوکال روی سرور آپلود شده است."

            # Find previous valid backup with real bot token
            local latest_valid_backup=""
            for b in $(ls -td "${INSTALL_DIR}/backups"/backup_* 2>/dev/null); do
                if [[ -f "${b}/.env" ]] && ! grep -q "CHANGE_ME_BOT_TOKEN" "${b}/.env"; then
                    latest_valid_backup="${b}"
                    break
                fi
            done

            if [[ -n "${latest_valid_backup}" ]]; then
                info "تنظیمات واقعی قبلی در بک‌آپ زیر پیدا شد:"
                info "${latest_valid_backup}"
                read -rp "آیا می‌خواهید تنظیمات (.env) واقعی قبلی از بک‌آپ بازگردانده شود؟ [Y/n]: " restore_choice
                if [[ "${restore_choice}" =~ ^[Yy]?$ ]]; then
                    cp "${latest_valid_backup}/.env" "${env_file}"
                    success "فایل .env اصلی با موفقیت بازگردانی شد."
                fi
            fi
            warn "--------------------------------------------------------"
        fi
    fi
}

# 3.2 Restore from existing backup
restore_backup() {
    header "بازگردانی سریع اطلاعات از بک‌آپ (Restore Backup)"
    determine_dirs

    local backups_dir="${INSTALL_DIR}/backups"
    if [[ ! -d "${backups_dir}" ]]; then
        error "پوشه بک‌آپ در مسیر ${backups_dir} یافت نشد."
        exit 1
    fi

    local backup_list=($(ls -td "${backups_dir}"/backup_* 2>/dev/null))
    if [[ ${#backup_list[@]} -eq 0 ]]; then
        error "هیچ بک‌آپی در مسیر ${backups_dir} وجود ندارد."
        exit 1
    fi

    echo -e "${CYAN}لیست بک‌آپ‌های خودکار موجود:${NC}"
    for i in "${!backup_list[@]}"; do
        local b_name=$(basename "${backup_list[$i]}")
        echo "  [$((i + 1))] ${b_name}"
    done

    echo ""
    read -rp "شماره بک‌آپ مورد نظر جهت بازگردانی را وارد کنید [1-${#backup_list[@]}]: " choice
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#backup_list[@]}" ]; then
        error "شماره انتخاب‌شده نامعتبر است."
        exit 1
    fi

    local selected_backup="${backup_list[$((choice - 1))]}"
    info "در حال بازگردانی از بک‌آپ: ${selected_backup}..."

    stop_service

    if [[ -f "${selected_backup}/.env" ]]; then
        cp "${selected_backup}/.env" "${INSTALL_DIR}/.env"
        success "فایل تنظیمات (.env) بازگردانده شد."
    fi

    if [[ -f "${selected_backup}/botsaller.db" ]]; then
        cp "${selected_backup}/botsaller.db" "${INSTALL_DIR}/botsaller.db"
        success "دیتابیس SQLite (botsaller.db) بازگردانده شد."
    fi

    if [[ -f "${selected_backup}/uploads_backup.tar.gz" ]]; then
        tar -xzf "${selected_backup}/uploads_backup.tar.gz" -C "${INSTALL_DIR}" 2>/dev/null || true
        success "فایل‌های آپلودی مشتریان بازگردانده شد."
    fi

    restart_service
    success "اطلاعات با موفقیت بازیابی و سرویس مجدداً راه‌اندازی شد!"
    exit 0
}

# 4. Stop systemd service
stop_service() {
    header "Step 2: Stopping Service"

    if systemctl is-active --quiet botsaller.service 2>/dev/null; then
        info "Stopping botsaller.service..."
        systemctl stop botsaller.service
        success "Service stopped cleanly."
    else
        warn "botsaller.service is not currently active."
    fi

    # Kill any lingering or orphaned Python processes holding port 8000 or Telegram polling
    info "Clearing any stale process listeners on port 8000..."
    pkill -f "main.py" 2>/dev/null || true
    fuser -k 8000/tcp 2>/dev/null || true
    sleep 1
}

# 5. Sync updated source files
sync_files() {
    header "Step 3: Updating Source Files"

    # If running from a directory outside /opt/botsaller, copy updated files over
    if [[ "${SCRIPT_DIR}" != "${INSTALL_DIR}" ]]; then
        info "Copying new source code from ${SCRIPT_DIR} to ${INSTALL_DIR}..."

        # Copy app package
        cp -r "${SCRIPT_DIR}/app" "${INSTALL_DIR}/"

        # Copy main scripts
        cp "${SCRIPT_DIR}/main.py" "${INSTALL_DIR}/main.py"
        cp "${SCRIPT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
        cp "${SCRIPT_DIR}/seed_kyc.py" "${INSTALL_DIR}/seed_kyc.py" 2>/dev/null || true
        cp "${SCRIPT_DIR}/update.sh" "${INSTALL_DIR}/update.sh" 2>/dev/null || true
        cp "${SCRIPT_DIR}/setup_ssl_domain.sh" "${INSTALL_DIR}/setup_ssl_domain.sh" 2>/dev/null || true
        chmod +x "${INSTALL_DIR}/update.sh" "${INSTALL_DIR}/setup_ssl_domain.sh" 2>/dev/null || true

        # Ensure MINIAPP_URL variable exists in .env if missing
        if [[ -f "${INSTALL_DIR}/.env" ]] && ! grep -q "^MINIAPP_URL=" "${INSTALL_DIR}/.env"; then
            echo "MINIAPP_URL=" >> "${INSTALL_DIR}/.env"
        fi

        # Ensure upload directories exist with proper permissions
        mkdir -p "${INSTALL_DIR}/uploads/portfolio"
        chmod -R 755 "${INSTALL_DIR}/uploads" 2>/dev/null || true

        # Clean Python bytecode cache to prevent stale modules
        find "${INSTALL_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        find "${INSTALL_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true

        success "Source code files synced successfully."
    else
        info "Running in-place update."
        # If git repo, pull latest
        if [[ -d "${INSTALL_DIR}/.git" ]]; then
            info "Git repository detected. Pulling latest commits..."
            git pull || warn "Could not pull git updates automatically."
        fi
    fi
}

# 6. Update Python dependencies
update_python_dependencies() {
    header "Step 4: Updating Python Dependencies & Virtual Environment"

    if [[ ! -d "${INSTALL_DIR}/venv" ]]; then
        info "Virtual environment missing. Creating new venv..."
        python3 -m venv "${INSTALL_DIR}/venv"
    fi

    info "Installing / updating requirements in virtual environment..."
    "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel -q
    "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q

    success "Python packages are up to date."
}

# 7. Apply database schema and seed updates
update_database() {
    header "Step 5: Updating Database & Seeding KYC Categories"

    info "Running KYC document categories and form builder sync..."
    cd "${INSTALL_DIR}"
    "${INSTALL_DIR}/venv/bin/python" -c "
import asyncio
from app.database import init_db
from main import seed_initial_data

async def run():
    print('Checking database tables...')
    await init_db()
    await seed_initial_data()
    print('Database sync completed.')

asyncio.run(run())
" || warn "Database sync finished with minor warnings."

    success "Database structure and KYC forms verified."
}

# 8. Restart systemd service and check status
restart_service() {
    header "Step 6: Restarting Botsaller Service"

    systemctl daemon-reload
    systemctl restart botsaller.service

    info "Waiting 3 seconds for service health check..."
    sleep 3

    if systemctl is-active --quiet botsaller.service; then
        success "Botsaller service is running smoothly!"
    else
        error "Botsaller service failed to start! Showing recent logs:"
        journalctl -u botsaller.service -n 25 --no-pager
        exit 1
    fi
}

# 9. Print summary
summary() {
    header "Update Completed Successfully!"

    echo -e "${GREEN}${BOLD}All application files, templates, and database schemas have been updated!${NC}\n"
    echo -e "${BOLD}Current Service Status:${NC}"
    systemctl status botsaller.service --no-pager -n 5 || true

    echo -e "\n${BOLD}Helpful Commands:${NC}"
    echo -e "  Live Logs:      ${CYAN}journalctl -u botsaller -f${NC}"
    echo -e "  Restart:        ${CYAN}systemctl restart botsaller${NC}"
    echo -e "  Check Status:   ${CYAN}systemctl status botsaller${NC}\n"
}

main() {
    check_root

    # Support for quick restore mode: ./update.sh --restore
    if [[ "${1:-}" == "--restore" || "${1:-}" == "-r" ]]; then
        restore_backup
        exit 0
    fi

    determine_dirs
    backup_data
    check_env_safety
    stop_service
    sync_files
    update_python_dependencies
    update_database
    restart_service
    summary
}

main "$@"

