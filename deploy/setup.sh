#!/usr/bin/env bash
# Set up Springform on a fresh Ubuntu 24.04 server: Docker, a firewall, automatic security
# updates, and the app behind Caddy (HTTPS) in /srv/springform. Safe to re-run.
#
#   sudo DOMAIN=crm.example.com deploy/setup.sh            # from a checkout
#   curl -fsSL https://raw.githubusercontent.com/wwilson1017/springform/master/deploy/setup.sh | sudo bash
#
# Without DOMAIN it asks. Optional: IMAGE=<a fork's image> (run `docker login ghcr.io` first if
# the image is private), NO_PULL=1 to run an IMAGE already loaded with `docker load` instead of
# pulling it, RCLONE_REMOTE=<remote:path> to schedule the off-site copy unattended.
set -euo pipefail

DIR=/srv/springform
RAW=https://raw.githubusercontent.com/wwilson1017/springform/master/deploy
DOCKER_KEY_FINGERPRINT=9DC858229FC7DD38854AE2D88D81803C0EBFCD88

[ "$(id -u)" = 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

# Ask on the terminal, even when the script itself arrives on stdin (curl | bash).
ask() {
  REPLY=
  if { : </dev/tty; } 2>/dev/null; then read -rp "$1" REPLY </dev/tty; fi
}

echo "== Packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg openssl cron ufw unattended-upgrades >/dev/null
if ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  fingerprint=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr/ {print $10; exit}')
  if [ "$fingerprint" != "$DOCKER_KEY_FINGERPRINT" ]; then
    rm -f /etc/apt/keyrings/docker.asc
    echo "Docker's apt key has fingerprint $fingerprint, expected $DOCKER_KEY_FINGERPRINT" >&2
    exit 1
  fi
  codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release)
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
    "https://download.docker.com/linux/ubuntu $codename stable" >/etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin >/dev/null
  systemctl enable --now docker >/dev/null 2>&1
fi

echo "== Firewall and automatic security updates"
# Docker publishes Caddy's 80/443 itself; the app publishes no port at all.
for port in 22 80 443; do ufw allow "$port/tcp" >/dev/null; done
ufw --force enable >/dev/null
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  >/etc/apt/apt.conf.d/20auto-upgrades

echo "== $DIR"
mkdir -p "$DIR/data"
src=
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/compose.yml" ]; then
  src=$(dirname "${BASH_SOURCE[0]}")
fi
for f in compose.yml Caddyfile deploy.sh offsite.sh; do
  if [ -n "$src" ]; then cp "$src/$f" "$DIR/$f"; else curl -fsSL "$RAW/$f" -o "$DIR/$f"; fi
done
chmod +x "$DIR/deploy.sh" "$DIR/offsite.sh"

if [ ! -f "$DIR/.env" ]; then
  DOMAIN=${DOMAIN:-}
  [ -n "$DOMAIN" ] || { ask "Domain for this server (its DNS must already point here): "; DOMAIN=$REPLY; }
  [ -n "$DOMAIN" ] || { echo "No domain: re-run with DOMAIN=crm.example.com" >&2; exit 1; }
  (
    umask 077
    cat >"$DIR/.env" <<EOF
DOMAIN=$DOMAIN
IMAGE=${IMAGE:-ghcr.io/wwilson1017/springform:latest}
PUBLIC_URL=https://$DOMAIN
SECRET_KEY=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
RESEND_API_KEY=
MAIL_FROM=
EOF
  )
  echo "Wrote $DIR/.env with new secrets"
fi
domain=$(sed -n 's/^DOMAIN=//p' "$DIR/.env")

echo "== Starting"
# </dev/null: under `curl | bash`, docker compose exec would otherwise eat the rest of this script.
"$DIR/deploy.sh" </dev/null

remote=${RCLONE_REMOTE:-}
if [ -z "$remote" ] && [ ! -f /etc/cron.d/springform-offsite ]; then
  ask "Off-site backups: an rclone remote path such as b2:my-bucket/springform (blank to skip): "
  remote=$REPLY
fi
if [ -n "$remote" ]; then
  command -v rclone >/dev/null || apt-get install -y -qq rclone >/dev/null
  if rclone listremotes 2>/dev/null | grep -qxF "${remote%%:*}:"; then
    echo "0 4 * * * root $DIR/offsite.sh '$remote' >>/var/log/springform-offsite.log 2>&1" \
      >/etc/cron.d/springform-offsite
    echo "Off-site copy scheduled nightly at 04:00 server time to $remote"
  else
    echo "rclone has no remote '${remote%%:*}'. Run 'rclone config', then re-run with RCLONE_REMOTE=$remote" >&2
  fi
fi

echo
if [ -f "$DIR/data/setup-token" ]; then
  echo "Open https://$domain and create the first admin with this one-time setup token:"
  echo "  $(cat "$DIR/data/setup-token")"
else
  echo "Springform is running at https://$domain (already set up)."
fi
echo "ENCRYPTION_KEY is in $DIR/.env. Keep a copy of that file off-site: without the key a"
echo "restored backup cannot read stored credentials."
