#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Iamafshiin/trader-agent.git}"
BRANCH="${BRANCH:-main}"
APP_USER=trader
APP_DIR=/opt/trader-agent
DATA_DIR=/var/lib/trader-agent
ENV_DIR=/etc/trader-agent

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

timedatectl set-timezone UTC
missing=""
for pkg in git curl ca-certificates; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing="$missing $pkg"
done
if [ -n "$missing" ]; then
  apt-get update -y || echo "apt-get update reported errors; continuing"
  apt-get install -y $missing
fi
timedatectl set-ntp true

id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/$APP_USER --shell /usr/sbin/nologin "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$DATA_DIR" "$DATA_DIR/home"
install -d -o root -g "$APP_USER" -m 0750 "$ENV_DIR"

if [ ! -f "$ENV_DIR/env" ]; then
  install -o root -g "$APP_USER" -m 0640 /dev/null "$ENV_DIR/env"
  printf 'TRADER_MODE=paper\nTRADER_DATA_DIR=%s\n' "$DATA_DIR" > "$ENV_DIR/env"
fi

if [ ! -x /home/$APP_USER/.local/bin/uv ]; then
  sudo -u "$APP_USER" -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

git config --system --add safe.directory "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin && git -C "$APP_DIR" checkout "$BRANCH" && git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" -H bash -c "cd $APP_DIR && ~/.local/bin/uv sync --locked --no-dev"

install -m 0644 "$APP_DIR"/deploy/systemd/*.service "$APP_DIR"/deploy/systemd/*.timer /etc/systemd/system/
install -m 0755 "$APP_DIR"/deploy/trader-kill /usr/local/sbin/trader-kill
install -m 0755 "$APP_DIR"/deploy/trader-cli /usr/local/bin/trader-cli
systemctl daemon-reload
systemctl enable --now trader-streams.service trader-candles.timer trader-report.timer trader-summary.timer
trader-cli check-config
systemctl --no-pager status trader-streams.service | head -5
