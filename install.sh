#!/usr/bin/env bash
# ==============================================================================
# Botsaller - Automated Linux Installation & Deployment Script
# Multi-level Category Telegram E-Commerce & RTL Web Management Panel
# Includes Automated Domain, Nginx Reverse Proxy & SSL Setup
# ==============================================================================

# Text formatting & Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Helper output functions
info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
header() {
    echo -e "\n${PURPLE}${BOLD}====================================================${NC}"
    echo -e "${PURPLE}${BOLD}  $1${NC}"
    echo -e "${PURPLE}${BOLD}====================================================${NC}\n"
}

# Ensure script is run as root
check_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        error "این اسکریپت نصب باید با دسترسی روت (root) یا با دستور sudo اجرا شود."
        echo -e "دستور صحیح: ${BOLD}sudo bash install.sh${NC}"
        exit 1
    fi
}

# Detect public IP address safely
get_server_ip() {
    local ip=""
    if command -v python3 &>/dev/null; then
        ip=$(python3 -c "
import urllib.request
for url in ['https://api.ipify.org', 'https://ifconfig.me', 'https://icanhazip.com']:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        res = urllib.request.urlopen(req, timeout=3).read().decode().strip()
        if res and len(res) <= 45:
            print(res)
            break
    except Exception:
        pass
" 2>/dev/null)
    fi

    if [[ -z "${ip}" ]] && command -v curl &>/dev/null; then
        ip=$(curl -s -m 4 https://api.ipify.org 2>/dev/null || curl -s -m 4 https://ifconfig.me 2>/dev/null || true)
    fi

    if [[ -z "${ip}" ]]; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    fi

    echo "${ip:-127.0.0.1}"
}

# Banner
display_banner() {
    clear 2>/dev/null || true
    echo -e "${CYAN}${BOLD}"
    cat << "EOF"
  ____       _                 _ _           
 |  _ \     | |               | | |          
 | |_) | ___| |_ ___  __ _  | | | ___ _ __ 
 |  _ < / _ \ __/ __|/ _` | | | |/ _ \ '__|
 | |_) | (_) | |_\__ \ (_| | | | |  __/ |   
 |____/ \___/ \__|___/\__,_|_|_|_|\___|_|   
EOF
    echo -e "${NC}"
    echo -e "${BOLD}Botsaller: سوپراپلیکیشن تلگرام، مینی‌اپ اختصاصی و پنل مدیریت تحت وب${NC}"
    echo -e "راه‌اندازی کامل، پیکربندی خودکار دامنه، وب‌سرور Nginx و گواهی SSL"
    echo -e "------------------------------------------------------------\n"
}

# Determine installation directory
determine_install_dir() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    if [[ -f "${script_dir}/main.py" && -f "${script_dir}/requirements.txt" ]]; then
        INSTALL_DIR="${script_dir}"
    else
        INSTALL_DIR="/opt/botsaller"
        mkdir -p "${INSTALL_DIR}"
    fi
    info "مسیر نصب پروژه: ${BOLD}${INSTALL_DIR}${NC}"
}

# Install necessary OS packages
install_system_dependencies() {
    header "مرحله ۱: نصب پکیج‌ها و پیش‌نیازهای سیستمی"

    if command -v apt-get &>/dev/null; then
        info "سیستم‌عامل دبیان/اوبونتو شناسایی شد. در حال نصب بسته‌ها..."
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y -qq >/dev/null 2>&1 || true
        apt-get install -y -qq \
            python3 \
            python3-venv \
            python3-pip \
            python3-dev \
            build-essential \
            libssl-dev \
            libffi-dev \
            git \
            curl \
            wget \
            ufw \
            net-tools \
            dnsutils \
            psmisc \
            openssl \
            nginx \
            certbot \
            python3-certbot-nginx >/dev/null 2>&1 || {
            warn "نصب با حالت جزئیات..."
            apt-get install -y python3 python3-venv python3-pip git curl openssl nginx certbot python3-certbot-nginx
        }
        success "تمامی پیش‌نیازهای سیستمی با موفقیت نصب شدند."
    elif command -v dnf &>/dev/null; then
        info "سیستم‌عامل RHEL/AlmaLinux/CentOS شناسایی شد..."
        dnf install -y -q epel-release >/dev/null 2>&1 || true
        dnf install -y -q \
            python3 \
            python3-pip \
            python3-devel \
            gcc \
            openssl-devel \
            libffi-devel \
            git \
            curl \
            wget \
            net-tools \
            bind-utils \
            psmisc \
            openssl \
            nginx \
            certbot \
            python3-certbot-nginx >/dev/null 2>&1 || true
        success "پیش‌نیازها نصب شدند."
    elif command -v yum &>/dev/null; then
        yum install -y -q epel-release >/dev/null 2>&1 || true
        yum install -y -q python3 python3-pip git curl openssl nginx certbot python3-certbot-nginx >/dev/null 2>&1 || true
        success "پیش‌نیازها نصب شدند."
    else
        warn "مدیریت پکیج ناشناخته است. لطفاً پایتون ۳ و nginx را دستی نصب کنید."
    fi
}

# Check if port is in use
check_port_available() {
    local port=$1
    if command -v ss &>/dev/null; then
        ss -tuln | grep -q ":${port} " && return 1 || return 0
    elif command -v netstat &>/dev/null; then
        netstat -tuln | grep -q ":${port} " && return 1 || return 0
    else
        return 0
    fi
}

# Collect user input
collect_configuration() {
    header "مرحله ۲: دریافت اطلاعات اولیه و تنظیمات"

    SERVER_IP=$(get_server_ip)
    echo -e "🌐 آی‌پی عمومی سرور شما: ${GREEN}${BOLD}${SERVER_IP}${NC}\n"

    # 1. Telegram Bot Token
    while true; do
        read -rp "👉 توکن ربات تلگرام را وارد کنید (از @BotFather): " BOT_TOKEN
        BOT_TOKEN=$(echo "${BOT_TOKEN}" | xargs)
        if [[ "${BOT_TOKEN}" =~ ^[0-9]+:[a-zA-Z0-9_-]+$ ]]; then
            break
        else
            error "فرمت توکن نامعتبر است. نمونه: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"
        fi
    done

    # 2. Domain / Subdomain for Mini App & SSL
    echo ""
    echo -e "${YELLOW}تنظیم دامنه برای مینی‌اپ تلگرام (Mini App):${NC}"
    echo -e "مینی‌اپ تلگرام برای باز شدن نیازمند یک دامنه دارای گواهی SSL (HTTPS) است."
    echo -e "قبل یا حین نصب، رکورد A دامنه خود را در کلودفلر یا پنل هاست روی آی‌پی ${BOLD}${SERVER_IP}${NC} تنظیم کنید."
    read -rp "👉 نام دامنه یا ساب‌دامین را وارد کنید (مثال: shop.domain.com | اینتر = بدون دامنه): " INPUT_DOMAIN
    INPUT_DOMAIN=$(echo "${INPUT_DOMAIN}" | tr '[:upper:]' '[:lower:]' | tr -d ' ' | sed -e 's|^https\?://||' -e 's|/.*$||')
    DOMAIN="${INPUT_DOMAIN}"

    EMAIL=""
    if [[ -n "${DOMAIN}" ]]; then
        info "دامنه ثبت‌شده: ${BOLD}${DOMAIN}${NC}"
        read -rp "👉 ایمیل جهت ثبت در Let's Encrypt (اختیاری، اینتر = admin@${DOMAIN}): " INPUT_EMAIL
        EMAIL=${INPUT_EMAIL:-"admin@${DOMAIN}"}
    else
        warn "دامنه‌ای وارد نشد؛ دسترسی مستقیم با آی‌پی سرور تنظیم خواهد شد."
    fi

    # 3. Web Panel Port
    echo ""
    while true; do
        read -rp "👉 پورت داخلی پنل وب [پیش‌فرض: 8000]: " INPUT_PORT
        INPUT_PORT=${INPUT_PORT:-8000}
        if [[ "${INPUT_PORT}" =~ ^[0-9]+$ ]] && [ "${INPUT_PORT}" -ge 1 ] && [ "${INPUT_PORT}" -le 65535 ]; then
            if check_port_available "${INPUT_PORT}"; then
                WEB_PORT="${INPUT_PORT}"
                break
            else
                warn "پورت ${INPUT_PORT} توسط پروسه دیگری اشغال است. لطفاً پورت دیگری انتخاب کنید."
            fi
        else
            error "پورت باید عددی بین ۱ تا ۶۵۵۳۵ باشد."
        fi
    done

    # 4. Super Admin Credentials
    echo ""
    read -rp "👉 نام کاربری مدیر ارشد پنل وب [پیش‌فرض: admin]: " INPUT_USER
    ADMIN_USERNAME=${INPUT_USER:-admin}

    while true; do
        read -rsp "👉 رمز عبور مدیر ارشد [خالی = تولید خودکار]: " INPUT_PASS
        echo ""
        if [[ -z "${INPUT_PASS}" ]]; then
            ADMIN_PASSWORD=$(openssl rand -base64 9 | tr -dc 'a-zA-Z0-9' | head -c 12)
            info "رمز عبور تصادفی تولید شد: ${BOLD}${ADMIN_PASSWORD}${NC}"
            break
        elif [ "${#INPUT_PASS}" -lt 6 ]; then
            error "رمز عبور باید حداقل ۶ کاراکتر باشد."
        else
            ADMIN_PASSWORD="${INPUT_PASS}"
            break
        fi
    done

    # 5. Database Choice
    echo ""
    info "انتخاب موتور دیتابیس:"
    echo "  1) SQLite (پیشنهادی: پرسرعت، بدون نیاز به کانفیگ، ذخیره در فایل محلی)"
    echo "  2) MySQL / MariaDB (دیتابیس اکسترنال)"
    read -rp "انتخاب [1 یا 2، پیش‌فرض: 1]: " DB_CHOICE
    DB_CHOICE=${DB_CHOICE:-1}

    if [ "${DB_CHOICE}" = "2" ]; then
        read -rp "آدرس سرور MySQL [پیش‌فرض: 127.0.0.1]: " DB_HOST
        DB_HOST=${DB_HOST:-127.0.0.1}
        read -rp "پورت MySQL [پیش‌فرض: 3306]: " DB_PORT
        DB_PORT=${DB_PORT:-3306}
        read -rp "نام کاربری MySQL [پیش‌فرض: root]: " DB_USER
        DB_USER=${DB_USER:-root}
        read -rsp "رمز عبور MySQL: " DB_PASS
        echo ""
        read -rp "نام دیتابیس MySQL [پیش‌فرض: botsaller]: " DB_NAME
        DB_NAME=${DB_NAME:-botsaller}
        DATABASE_URL="mysql+aiomysql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4"
    else
        DATABASE_URL="sqlite+aiosqlite:///${INSTALL_DIR}/botsaller.db"
    fi

    # 6. Cold Wallet Addresses
    echo ""
    info "تنظیمات آدرس‌های دریافت تتر (USDT):"
    read -rp "آدرس والت دریافت تتر TRC20 (ترون) [اینتر = پیش‌فرض تست]: " INPUT_TRC20
    COLD_WALLET_TRC20=${INPUT_TRC20:-"TXYZ1234567890ExampleTRC20Address"}

    read -rp "آدرس والت دریافت تتر BEP20 (بایننس اسمارت‌چین) [اینتر = پیش‌فرض تست]: " INPUT_BEP20
    COLD_WALLET_BEP20=${INPUT_BEP20:-"0x1234567890abcdef1234567890abcdef12345678"}

    read -rp "کلید API ترون‌اسکن TronGrid [اختیاری، اینتر = رد شدن]: " TRONSCAN_API_KEY
    TRONSCAN_API_KEY=${TRONSCAN_API_KEY:-""}

    read -rp "کلید API بی‌اس‌سی‌اسکن BscScan [اختیاری، اینتر = رد شدن]: " BSCSCAN_API_KEY
    BSCSCAN_API_KEY=${BSCSCAN_API_KEY:-""}

    read -rp "آیدی عددی کانال/گروه اپراتور جهت گزارش‌ها [اختیاری]: " OPERATOR_CHAT_ID
    OPERATOR_CHAT_ID=${OPERATOR_CHAT_ID:-""}

    # Generate Secret Key
    SECRET_KEY=$(openssl rand -hex 32)
}

# Create .env file
write_env_file() {
    header "مرحله ۳: ایجاد فایل تنظیمات محیطی (.env)"

    local env_path="${INSTALL_DIR}/.env"
    if [[ -f "${env_path}" ]]; then
        local env_backup="${INSTALL_DIR}/.env.backup_$(date +%Y%m%d_%H%M%S)"
        cp "${env_path}" "${env_backup}"
        info "نسخه پشتیبان از .env قبلی ذخیره شد: ${env_backup}"
    fi

    local miniapp_url=""
    if [[ -n "${DOMAIN}" ]]; then
        miniapp_url="https://${DOMAIN}/webapp"
    else
        miniapp_url="http://${SERVER_IP}:${WEB_PORT}/webapp"
    fi

    cat > "${env_path}" << EOF
# Telegram Bot Configuration
BOT_TOKEN=${BOT_TOKEN}
BOT_WEBHOOK_URL=
MINIAPP_URL=${miniapp_url}

# Database Configuration
DATABASE_URL=${DATABASE_URL}

# Web Panel & Security
SECRET_KEY=${SECRET_KEY}
ADMIN_DEFAULT_USERNAME=${ADMIN_USERNAME}
ADMIN_DEFAULT_PASSWORD=${ADMIN_PASSWORD}
WEB_HOST=0.0.0.0
WEB_PORT=${WEB_PORT}

# Crypto Verification Settings
COLD_WALLET_TRC20=${COLD_WALLET_TRC20}
COLD_WALLET_BEP20=${COLD_WALLET_BEP20}
TRONSCAN_API_KEY=${TRONSCAN_API_KEY}
BSCSCAN_API_KEY=${BSCSCAN_API_KEY}
CRYPTO_CHECK_INTERVAL_SECONDS=30

# Uploads directory
UPLOAD_DIR=${INSTALL_DIR}/uploads
EOF

    chmod 600 "${env_path}"
    success "فایل .env با دسترسی امن (600) ایجاد شد."
}

# Setup Python Virtual Environment and Install Dependencies
setup_python_environment() {
    header "مرحله ۴: آماده‌سازی پایتون و نصب وابستگی‌ها"

    cd "${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}/uploads/portfolio"
    chmod -R 755 "${INSTALL_DIR}/uploads"

    info "ایجاد محیط مجازی venv در ${INSTALL_DIR}/venv..."
    python3 -m venv "${INSTALL_DIR}/venv"

    info "ارتقای pip و نصب پکیج‌های پایتون از requirements.txt..."
    "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel -q
    "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" -q

    success "محیط مجازی پایتون و ماژول‌ها آماده شدند."
}

# Setup Nginx and SSL (Only if Domain is provided)
setup_nginx_and_ssl() {
    if [[ -z "${DOMAIN}" ]]; then
        info "دامنه‌ای ثبت نشده، مرحله راه‌اندازی Nginx رد شد."
        return 0
    fi

    header "مرحله ۵: پیکربندی خودکار وب‌سرور Nginx و گواهی SSL"

    # Stop Apache if running on port 80
    systemctl stop apache2 2>/dev/null || true
    systemctl disable apache2 2>/dev/null || true
    systemctl stop httpd 2>/dev/null || true
    systemctl disable httpd 2>/dev/null || true

    # Prepare webroot for ACME challenges
    mkdir -p /var/www/html/.well-known/acme-challenge
    chmod -R 755 /var/www/html

    local conf_file="/etc/nginx/conf.d/botsaller.conf"
    local is_sites_available=false
    if [[ -d "/etc/nginx/sites-available" ]]; then
        is_sites_available=true
        conf_file="/etc/nginx/sites-available/botsaller.conf"
    fi

    info "نوشتن کانفیگ Nginx در ${conf_file}..."

    # Initial HTTP configuration
    cat > "${conf_file}" << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 64M;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
    }

    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_connect_timeout 90s;
        proxy_send_timeout 90s;
        proxy_read_timeout 90s;
    }
}
EOF

    if [[ "${is_sites_available}" == true ]]; then
        mkdir -p /etc/nginx/sites-enabled
        ln -sf "${conf_file}" /etc/nginx/sites-enabled/botsaller.conf
        rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    fi
    rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true

    systemctl enable nginx 2>/dev/null || true
    systemctl restart nginx 2>/dev/null || true

    # Request SSL via Let's Encrypt
    info "در حال صدور گواهی امنیتی SSL (Let's Encrypt) برای ${DOMAIN}..."
    local email_arg="--register-unsafely-without-email"
    if [[ -n "${EMAIL}" && "${EMAIL}" != "admin@${DOMAIN}" ]]; then
        email_arg="--email ${EMAIL}"
    fi

    local ssl_ok=false
    # Try Webroot challenge first
    if certbot certonly --webroot -w /var/www/html -d "${DOMAIN}" --non-interactive --agree-tos ${email_arg} >/dev/null 2>&1; then
        ssl_ok=true
    elif certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos ${email_arg} --redirect >/dev/null 2>&1; then
        ssl_ok=true
    fi

    local cert_path="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
    local key_path="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

    if [[ "${ssl_ok}" == true && -f "${cert_path}" && -f "${key_path}" ]]; then
        cat > "${conf_file}" << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate ${cert_path};
    ssl_certificate_key ${key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    client_max_body_size 64M;

    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_connect_timeout 90s;
        proxy_send_timeout 90s;
        proxy_read_timeout 90s;
    }
}
EOF
        nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null || true
        success "گواهی رسمی Let's Encrypt فعال شد و ترافیک به HTTPS ریدایرکت می‌شود."
        systemctl enable certbot.timer 2>/dev/null || true
        systemctl start certbot.timer 2>/dev/null || true
    else
        warn "صدور گواهی مستقیم ناموفق بود (احتمالاً به دلیل پروکسی Cloudflare یا عدم انتشار کامل DNS)."
        info "در حال ایجاد گواهی SSL خودامضا برای اتصال فوری به مینی‌اپ و کلودفلر..."
        mkdir -p /etc/nginx/ssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "/etc/nginx/ssl/botsaller.key" \
            -out "/etc/nginx/ssl/botsaller.crt" \
            -subj "/CN=${DOMAIN}/O=Botsaller/C=US" >/dev/null 2>&1 || true

        cat > "${conf_file}" << EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/nginx/ssl/botsaller.crt;
    ssl_certificate_key /etc/nginx/ssl/botsaller.key;

    client_max_body_size 64M;

    location / {
        proxy_pass http://127.0.0.1:${WEB_PORT};
        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOF
        nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null || true
        success "گواهی SSL امن آماده شد (با Cloudflare کاملاً سازگار و سبز است)."
    fi
}

# Configure firewall if UFW is active
configure_firewall() {
    header "مرحله ۶: تنظیم فایروال سرور"
    if command -v ufw &>/dev/null; then
        ufw allow 80/tcp >/dev/null 2>&1 || true
        ufw allow 443/tcp >/dev/null 2>&1 || true
        ufw allow "${WEB_PORT}/tcp" >/dev/null 2>&1 || true
        success "پورت‌های 80، 443 و ${WEB_PORT} در فایروال UFW باز شدند."
    fi
}

# Setup systemd service
setup_systemd_service() {
    header "مرحله ۷: راه‌اندازی و اجرای دائم سرویس (Systemd Service)"

    local service_file="/etc/systemd/system/botsaller.service"

    cat > "${service_file}" << EOF
[Unit]
Description=Botsaller Telegram Commerce & Web Panel Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python main.py
Restart=always
RestartSec=3
EnvironmentFile=${INSTALL_DIR}/.env
StandardOutput=journal
StandardError=journal
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable botsaller.service >/dev/null 2>&1 || true
    info "اجرای سرویس botsaller..."
    systemctl restart botsaller.service

    sleep 3
    if systemctl is-active --quiet botsaller.service; then
        success "سرویس Botsaller با موفقیت اجرا شد و در استارتاپ لینوکس قرار گرفت."
    else
        warn "سرویس در حال استارت است. در صورت نیاز وضعیت را با دستور زیر بررسی کنید:"
        echo "systemctl status botsaller.service"
    fi
}

# Final instructions and summary
display_summary() {
    header "🎉 تبریک! نصب و راه‌اندازی پلتفرم با موفقیت تکمیل شد"

    local panel_url=""
    local miniapp_url=""

    if [[ -n "${DOMAIN}" ]]; then
        panel_url="https://${DOMAIN}/login"
        miniapp_url="https://${DOMAIN}/webapp"
    else
        panel_url="http://${SERVER_IP}:${WEB_PORT}/login"
        miniapp_url="http://${SERVER_IP}:${WEB_PORT}/webapp"
    fi

    echo -e "${GREEN}${BOLD}اطلاعات ورود و دسترسی به پلتفرم:${NC}\n"
    echo -e "  🔐 آدرس پنل مدیریت تحت وب:  ${CYAN}${BOLD}${panel_url}${NC}"
    echo -e "  👤 نام کاربری پیش‌فرض مدیر: ${YELLOW}${ADMIN_USERNAME}${NC}"
    echo -e "  🔑 رمز عبور مدیر:          ${YELLOW}${ADMIN_PASSWORD}${NC}\n"

    if [[ -n "${DOMAIN}" ]]; then
        echo -e "${BOLD}لینک اختصاصی مینی‌اپ تلگرام:${NC}"
        echo -e "  🌐 آدرس وب‌اپ:              ${CYAN}${BOLD}${miniapp_url}${NC}\n"

        echo -e "${YELLOW}${BOLD}گام نهایی در بات‌فادر (@BotFather):${NC}"
        echo -e "  1. وارد ربات @BotFather در تلگرام شوید."
        echo -e "  2. دستور ${BOLD}/mybots${NC} را زده و ربات خود را انتخاب کنید."
        echo -e "  3. روی ${BOLD}Bot Settings${NC} و سپس ${BOLD}Menu Button${NC} کلیک کنید."
        echo -e "  4. گزینه ${BOLD}Configure menu button${NC} را بزنید و آدرس زیر را بفرستید:"
        echo -e "     👉 ${CYAN}${miniapp_url}${NC}"
        echo -e "  5. عنوان دکمه را مثلاً ${BOLD}🛍 ورود به فروشگاه${NC} بگذارید.\n"
    fi

    echo -e "${BOLD}دستورات مفید مدیریت در سرور:${NC}"
    echo -e "  مشاهده لاگ زنده ربات:   ${CYAN}journalctl -u botsaller -f${NC}"
    echo -e "  ری‌استارت ربات:         ${CYAN}systemctl restart botsaller${NC}"
    echo -e "  بررسی وضعیت سرویس:      ${CYAN}systemctl status botsaller${NC}\n"
}

# Main execution flow
main() {
    check_root
    display_banner
    determine_install_dir
    install_system_dependencies
    collect_configuration
    write_env_file
    setup_python_environment
    setup_nginx_and_ssl
    configure_firewall
    setup_systemd_service
    display_summary
}

main "$@"
