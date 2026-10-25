#!/bin/bash
# Free HTTPS with Let's Encrypt. Run on the server once a domain points at it, e.g. your own domain or
# <ip-with-dashes>.sslip.io. Running it means you accept the Let's Encrypt subscriber agreement.
#   sudo bash enable_https.sh reels.example.com you@example.com
set -euo pipefail
DOMAIN="$1"; EMAIL="$2"
[ -x /opt/certbot/bin/certbot ] || { python3.12 -m venv /opt/certbot && /opt/certbot/bin/pip install -q certbot certbot-nginx; }
sed -i "s/server_name _;/server_name $DOMAIN;/" /etc/nginx/nginx.conf
/opt/certbot/bin/certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --redirect
sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$DOMAIN|; s|^COOKIE_SECURE=.*|COOKIE_SECURE=true|" /etc/claude-blooded.env
systemctl restart claude-blooded-api
echo "0 3 * * * root /opt/certbot/bin/certbot renew -q" > /etc/cron.d/certbot-renew
echo "https://$DOMAIN is live"
