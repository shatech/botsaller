#!/usr/bin/env bash
# ==============================================================================
# Botsaller - Automated Domain & SSL Setup for Telegram Mini App (TMA)
# Fully automated, crash-proof domain setup, Nginx reverse proxy, and SSL certificate.
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

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
header() {
    echo -e "\n${PURPLE}${BOLD}====================================================${NC}"
    echo -e "${PURPLE}${BOLD}  $1${NC}"
    echo -e "${PURPLE}${BOLD}====================================================${NC}\n"
}

# 1. Check Root Privileges
check_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        error "این اسکریپت باید با دسترسی روت (root) یا با دستور sudo اجرا شود."
        echo -e "لطفاً دستور را به این صورت اجرا کنید: ${BOLD}sudo bash setup_ssl_domain.sh${NC}"
        exit 1
    fi
}

# 2. Detect Botsaller Installation Directory
find_install_dir() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${SCRIPT_DIR}/main.py" && -f "${SCRIPT_DIR}/.env" ]]; then
        INSTALL_DIR="${SCRIPT_DIR}"
    elif [[ -d "/opt/botsaller" && -f "/opt/botsaller/main.py" ]]; then
        INSTALL_DIR="/opt/botsaller"
    elif [[ -f "${SCRIPT_DIR}/main.py" ]]; then
        INSTALL_DIR="${SCRIPT_DIR}"
    else
        INSTALL_DIR="/opt/botsaller"
    fi
    info "مسیر نصب Botsaller: ${BOLD}${INSTALL_DIR}${NC}"
}

# 3. Detect Server IP safely using Python or curl
get_server_ip() {
    local ip=""
    if command -v python3 &>/dev/null; then
        ip=$(python3 -c "
import urllib.request, socket
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

# 4. Display Banner
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
    echo -e "${BOLD}تنظیم خودکار دامنه، وب‌سرور Nginx و گواهی SSL (Let's Encrypt)${NC}"
    echo -e "ویژه اتصال پرسرعت و امن مینی‌اپ تلگرام (Telegram Mini App)\n"
    echo -e "------------------------------------------------------------\n"
}

# 5. Pre-install Essential Tools
install_prerequisites() {
    header "مرحله ۱: بررسی و نصب پیش‌نیازهای سیستمی"
    info "در حال بررسی و آماده‌سازی پکیج‌های پایه..."

    if command -v apt-get &>/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y -qq >/dev/null 2>&1 || true
        apt-get install -y -qq curl wget dnsutils ufw psmisc python3 python3-pip >/dev/null 2>&1 || true
    elif command -v dnf &>/dev/null; then
        dnf install -y epel-release -q >/dev/null 2>&1 || true
        dnf install -y curl wget bind-utils psmisc python3 >/dev/null 2>&1 || true
    elif command -v yum &>/dev/null; then
        yum install -y epel-release -q >/dev/null 2>&1 || true
        yum install -y curl wget bind-utils psmisc python3 >/dev/null 2>&1 || true
    fi
    success "ابزارهای پایه آماده هستند."
}

# 6. Collect Domain and Email
collect_info() {
    header "مرحله ۲: دریافت اطلاعات دامنه"

    SERVER_IP=$(get_server_ip)
    echo -e "🌐 آی‌پی عمومی این سرور: ${GREEN}${BOLD}${SERVER_IP}${NC}"
    echo -e "${YELLOW}توجه:${NC} قبل از ادامه، در کلودفلر یا پنل هاست خود یک ${BOLD}رکورد A${NC} با آی‌پی فوق برای دامنه یا ساب‌دامین خود ثبت کنید.\n"

    # Domain argument or prompt
    if [[ -n "${1:-}" ]]; then
        DOMAIN="${1}"
    else
        while true; do
            read -rp "👉 لطفاً نام دامنه یا زیردامنه خود را وارد کنید (مثال: shop.yourdomain.com): " DOMAIN
            DOMAIN=$(echo "${DOMAIN}" | tr '[:upper:]' '[:lower:]' | tr -d ' ' | sed -e 's|^https\?://||' -e 's|/.*$||')
            if [[ "${DOMAIN}" =~ ^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$ ]]; then
                break
            else
                error "فرمت دامنه معتبر نیست. لطفاً مجدداً بدون http یا اسلش وارد کنید."
            fi
        done
    fi

    # Email for Let's Encrypt
    if [[ -n "${2:-}" ]]; then
        EMAIL="${2}"
    else
        read -rp "👉 ایمیل جهت دریافت اخطارهای انقضای SSL (اینتر = admin@${DOMAIN}): " EMAIL
        EMAIL=${EMAIL:-"admin@${DOMAIN}"}
    fi

    # Read backend port from .env if present
    BACKEND_PORT=8000
    if [[ -f "${INSTALL_DIR}/.env" ]]; then
        ENV_PORT=$(grep -E "^WEB_PORT=" "${INSTALL_DIR}/.env" | cut -d '=' -f2 | tr -d ' ' || true)
        if [[ -n "${ENV_PORT}" && "${ENV_PORT}" =~ ^[0-9]+$ ]]; then
            BACKEND_PORT="${ENV_PORT}"
        fi
    fi
    info "پورت پلتفرم Botsaller: ${BOLD}${BACKEND_PORT}${NC}"
}

# 7. Verify DNS Resolution using Python socket
verify_dns() {
    header "مرحله ۳: بررسی اتصال DNS دامنه"
    info "در حال بررسی وضعیت رکورد DNS برای دامنه ${BOLD}${DOMAIN}${NC}..."

    RESOLVED_IP=""
    if command -v python3 &>/dev/null; then
        RESOLVED_IP=$(python3 -c "
import socket, sys
try:
    print(socket.gethostbyname('${DOMAIN}'))
except Exception:
    sys.exit(0)
" 2>/dev/null || true)
    fi

    if [[ -z "${RESOLVED_IP}" ]]; then
        RESOLVED_IP=$(getent hosts "${DOMAIN}" 2>/dev/null | awk '{print $1}' | head -n 1 || true)
    fi

    if [[ -n "${RESOLVED_IP}" ]]; then
        info "آی‌پی شناسایی‌شده دامنه در اینترنت: ${BOLD}${RESOLVED_IP}${NC}"
        if [[ "${RESOLVED_IP}" == "${SERVER_IP}" ]]; then
            success "عالی است! دامنه مستقیماً به آی‌پی سرور شما هدایت شده است."
        else
            warn "دامنه به آی‌پی ${RESOLVED_IP} اشاره دارد که با آی‌پی سرور (${SERVER_IP}) متفاوت است."
            warn "این موضوع در صورت فعال بودن پروکسی کلودفلر (Cloudflare CDN Proxy - ابر نارنجی) کاملاً طبیعی است."
            echo -e "${YELLOW}آیا می‌خواهید با همین شرایط نصب ادامه یابد؟${NC}"
            read -rp "ادامه نصب؟ [Y/n]: " CONTINUE_DNS
            CONTINUE_DNS=${CONTINUE_DNS:-"y"}
            if [[ ! "${CONTINUE_DNS}" =~ ^[Yy]$ ]]; then
                error "عملیات متوقف شد. لطفاً ابتدا رکورد A دامنه را بررسی و اصلاح فرمایید."
                exit 1
            fi
        fi
    else
        warn "دامنه ${DOMAIN} هنوز در اینترنت شناسایی نمی‌شود (احتمالاً تازه ثبت کرده‌اید یا هنوز ست نشده)."
        echo -e "${YELLOW}می‌توانیم وب‌سرور Nginx را کانفیگ کنیم و بعداً SSL را صادر کنیم.${NC}"
        read -rp "آیا ادامه دهیم؟ [Y/n]: " CONTINUE_ANYWAY
        CONTINUE_ANYWAY=${CONTINUE_ANYWAY:-"y"}
        if [[ ! "${CONTINUE_ANYWAY}" =~ ^[Yy]$ ]]; then
            error "عملیات لغو شد."
            exit 1
        fi
    fi
}

# 8. Install Nginx and Certbot & Free Port 80
install_webserver() {
    header "مرحله ۴: نصب و آماده‌سازی Nginx و Certbot"

    # Stop Apache if it is running and holding port 80
    if systemctl is-active --quiet apache2 2>/dev/null; then
        warn "سرویس Apache2 در حال اجرا روی پورت 80 بود. در حال توقف آن..."
        systemctl stop apache2 2>/dev/null || true
        systemctl disable apache2 2>/dev/null || true
    fi
    if systemctl is-active --quiet httpd 2>/dev/null; then
        systemctl stop httpd 2>/dev/null || true
        systemctl disable httpd 2>/dev/null || true
    fi

    # Install Nginx & Certbot
    if command -v apt-get &>/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get install -y -qq nginx certbot python3-certbot-nginx >/dev/null 2>&1 || {
            warn "تلاش مجدد برای نصب Nginx..."
            apt-get update -y
            apt-get install -y nginx certbot python3-certbot-nginx
        }
    elif command -v dnf &>/dev/null; then
        dnf install -y nginx certbot python3-certbot-nginx -q >/dev/null 2>&1 || true
    elif command -v yum &>/dev/null; then
        yum install -y nginx certbot python3-certbot-nginx -q >/dev/null 2>&1 || true
    fi

    # Ensure webroot directory exists for ACME challenges
    mkdir -p /var/www/html/.well-known/acme-challenge
    chmod -R 755 /var/www/html

    # Enable and start Nginx
    systemctl enable nginx 2>/dev/null || true
    systemctl start nginx 2>/dev/null || true
    success "Nginx و Certbot آماده هستند."
}

# 9. Configure Nginx Reverse Proxy
configure_nginx() {
    header "مرحله ۵: پیکربندی ریورس‌پراکسی Nginx"

    local conf_file="/etc/nginx/conf.d/botsaller.conf"
    local is_sites_available=false

    if [[ -d "/etc/nginx/sites-available" ]]; then
        is_sites_available=true
        conf_file="/etc/nginx/sites-available/botsaller.conf"
    fi

    info "ایجاد فایل تنظیمات در ${conf_file}..."

    # Create Nginx virtual host with ACME challenge support
    cat > "${conf_file}" << EOF
# Botsaller Reverse Proxy Configuration for ${DOMAIN}
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Maximum upload size for documents and images
    client_max_body_size 64M;

    # ACME Challenge for Let's Encrypt SSL
    location /.well-known/acme-challenge/ {
        root /var/www/html;
        allow all;
    }

    # Proxy to FastAPI / Botsaller Backend
    location / {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_http_version 1.1;

        # WebSocket support
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Forwarded Client Information
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Timeouts
        proxy_connect_timeout 90s;
        proxy_send_timeout 90s;
        proxy_read_timeout 90s;
    }
}
EOF

    # Symlink on Debian/Ubuntu
    if [[ "${is_sites_available}" == true ]]; then
        mkdir -p /etc/nginx/sites-enabled
        ln -sf "${conf_file}" /etc/nginx/sites-enabled/botsaller.conf
        rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    fi

    # Disable default conf on CentOS/RHEL if present
    rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true

    # SELinux support on RHEL/CentOS
    if command -v setsebool &>/dev/null; then
        setsebool -P httpd_can_network_connect 1 2>/dev/null || true
    fi

    # Test Nginx configuration
    info "تست صحت ساختار Nginx..."
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
        success "تنظیمات Nginx با موفقیت فعال شد."
    else
        warn "خطا در تست Nginx! خروجی بررسی:"
        nginx -t || true
        error "لطفاً خطای نمایش‌داده‌شده را بررسی فرمایید."
    fi
}

# 10. Open Firewall Ports
configure_firewall() {
    if command -v ufw &>/dev/null; then
        ufw allow 80/tcp >/dev/null 2>&1 || true
        ufw allow 443/tcp >/dev/null 2>&1 || true
        ufw allow "${BACKEND_PORT}/tcp" >/dev/null 2>&1 || true
    fi
    if command -v firewall-cmd &>/dev/null; then
        firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
        firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
    fi
}

# 11. Request SSL Certificate (Let's Encrypt / Fallback)
request_ssl() {
    header "مرحله ۶: دریافت و فعال‌سازی گواهی امنیتی SSL"
    info "درخواست صدور گواهی SSL از Let's Encrypt برای ${BOLD}${DOMAIN}${NC}..."

    local email_arg="--register-unsafely-without-email"
    if [[ -n "${EMAIL}" && "${EMAIL}" != "admin@${DOMAIN}" ]]; then
        email_arg="--email ${EMAIL}"
    fi

    local ssl_success=false

    # Attempt 1: Try Webroot challenge (Most reliable, works behind Cloudflare too)
    info "تلاش برای دریافت گواهی از طریق استاندارد Webroot..."
    if certbot certonly --webroot -w /var/www/html -d "${DOMAIN}" --non-interactive --agree-tos ${email_arg} >/dev/null 2>&1; then
        ssl_success=true
    fi

    # Attempt 2: If attempt 1 failed, try Nginx plugin
    if [[ "${ssl_success}" == false ]]; then
        info "تلاش از طریق ماژول اختصاصی Nginx Certbot..."
        if certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos ${email_arg} --redirect >/dev/null 2>&1; then
            ssl_success=true
        fi
    fi

    if [[ "${ssl_success}" == true ]]; then
        # If certbot certonly was used, configure SSL block in Nginx
        local cert_path="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
        local key_path="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

        if [[ -f "${cert_path}" && -f "${key_path}" ]]; then
            local conf_file="/etc/nginx/conf.d/botsaller.conf"
            if [[ -d "/etc/nginx/sites-available" ]]; then
                conf_file="/etc/nginx/sites-available/botsaller.conf"
            fi

            cat > "${conf_file}" << EOF
# Botsaller Secure Reverse Proxy Configuration with SSL for ${DOMAIN}
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
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
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
        fi

        success "گواهی امنیتی Let's Encrypt با موفقیت صادر و بر روی Nginx فعال شد!"
        systemctl enable certbot.timer 2>/dev/null || true
        systemctl start certbot.timer 2>/dev/null || true
    else
        warn "صدور گواهی از Let's Encrypt ناموفق بود."
        echo -e "${YELLOW}دلایل احتمالی:${NC}"
        echo -e " 1. رکورد DNS هنوز در سرورهای جهانی Let's Encrypt ثبت نشده (چند دقیقه صبر کنید)."
        echo -e " 2. اگر از Cloudflare استفاده می‌کنید، موقتاً پروکسی (ابر نارنجی) را خاموش (DNS Only) کنید."
        echo -e "\nدر حال ایجاد یک گواهی خودامضا (Self-Signed) امن برای اینکه مینی‌اپ و سایت معطل نمانند..."

        mkdir -p /etc/nginx/ssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "/etc/nginx/ssl/botsaller.key" \
            -out "/etc/nginx/ssl/botsaller.crt" \
            -subj "/CN=${DOMAIN}/O=Botsaller/C=US" >/dev/null 2>&1 || true

        if [[ -f "/etc/nginx/ssl/botsaller.crt" ]]; then
            local conf_file="/etc/nginx/conf.d/botsaller.conf"
            if [[ -d "/etc/nginx/sites-available" ]]; then
                conf_file="/etc/nginx/sites-available/botsaller.conf"
            fi

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
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
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
            success "گواهی SSL آماده شد (اگر از کلودفلر استفاده کنید فوراً سبز و ولید است)."
        fi
    fi
}

# 12. Update .env with MINIAPP_URL and Restart Botsaller
update_env_and_restart() {
    header "مرحله ۷: بروزرسانی متغیرها و ری‌استارت سرویس"

    local env_file="${INSTALL_DIR}/.env"
    local https_miniapp_url="https://${DOMAIN}/webapp"

    if [[ -f "${env_file}" ]]; then
        info "ثبت آدرس مینی‌اپ در ${env_file}..."
        if grep -q "^MINIAPP_URL=" "${env_file}"; then
            sed -i "s|^MINIAPP_URL=.*|MINIAPP_URL=${https_miniapp_url}|g" "${env_file}"
        else
            echo "MINIAPP_URL=${https_miniapp_url}" >> "${env_file}"
        fi
        success "متغیر MINIAPP_URL با مقدار ${BOLD}${https_miniapp_url}${NC} ذخیره شد."

        if systemctl list-unit-files | grep -q "botsaller.service"; then
            info "راه‌اندازی مجدد سرویس Botsaller..."
            systemctl daemon-reload 2>/dev/null || true
            systemctl restart botsaller.service 2>/dev/null || true
            sleep 2
            if systemctl is-active --quiet botsaller.service 2>/dev/null; then
                success "سرویس Botsaller با موفقیت ری‌استارت شد و در حال اجراست."
            else
                warn "سرویس Botsaller متوقف است. می‌توانید با دستور systemctl restart botsaller آن را اجرا کنید."
            fi
        fi
    else
        warn "فایل .env در ${INSTALL_DIR} یافت نشد. لطفاً MINIAPP_URL=${https_miniapp_url} را دستی به فایل .env اضافه کنید."
    fi
}

# 13. Summary
show_summary() {
    header "پیکربندی دامنه با موفقیت به پایان رسید! 🎉"

    local miniapp_url="https://${DOMAIN}/webapp"
    local admin_url="https://${DOMAIN}/admin/dashboard"

    echo -e "${GREEN}${BOLD}آدرس‌های دسترسی آماده استفاده:${NC}\n"
    echo -e "  🌐 آدرس مینی‌اپ تلگرام:   ${CYAN}${BOLD}${miniapp_url}${NC}"
    echo -e "  🔐 پنل مدیریت تحت وب:    ${CYAN}${BOLD}${admin_url}${NC}"
    echo -e "  🛡️ وضعیت امنیتی:          ${GREEN}فعال با ریدایرکت خودکار به HTTPS${NC}\n"

    echo -e "${YELLOW}${BOLD}تنظیم نهایی دکمه مینی‌اپ در @BotFather:${NC}"
    echo -e " 1. در تلگرام وارد ربات ${BOLD}@BotFather${NC} شوید."
    echo -e " 2. دستور ${BOLD}/mybots${NC} را زده و ربات خود را انتخاب کنید."
    echo -e " 3. مسیر: ${BOLD}Bot Settings -> Menu Button -> Configure menu button${NC}"
    echo -e " 4. لینک زیر را به عنوان URL مینی‌اپ ارسال فرمایید:"
    echo -e "    👉 ${CYAN}${miniapp_url}${NC}"
    echo -e " 5. عنوان دکمه را مثلاً ${BOLD}🛍 ورود به فروشگاه${NC} بگذارید.\n"
}

# Main Runner
main() {
    check_root
    find_install_dir
    display_banner
    install_prerequisites
    collect_info "${1:-}" "${2:-}"
    verify_dns
    install_webserver
    configure_nginx
    configure_firewall
    request_ssl
    update_env_and_restart
    show_summary
}

main "$@"
