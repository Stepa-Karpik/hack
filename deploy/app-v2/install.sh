#!/usr/bin/env bash
# Install / update the app release on the server (run as root).
#   bash install.sh /tmp/app-v2.tar.gz [stage]
# Stages: release venv model service nginx switch. Without a stage, runs all of them in order.
# The previous web-v1 release, its venv and its service unit are left on disk for rollback.
set -euo pipefail
ARCHIVE=${1:?archive}
STAGE=${2:-all}
OPT=/opt/online-dekanat
REL=$OPT/releases/app-v2
VENV=$OPT/venv-app
STATE=$OPT/app-state
MODEL=$OPT/models/paddle-vl-1.6
run() { [ "$STAGE" = all ] || [ "$STAGE" = "$1" ]; }

if run release; then
  if [ -d "$REL" ]; then mv "$REL" "$REL.prev-$(date +%Y%m%d-%H%M%S)"; fi
  mkdir -p "$REL"
  tar -xzf "$ARCHIVE" -C "$REL"
  chown -R root:root "$REL"; chmod -R a+rX,go-w "$REL"
  id online-dekanat >/dev/null 2>&1 || useradd --system --home "$OPT" --shell /usr/sbin/nologin online-dekanat
  install -d -o online-dekanat -g online-dekanat -m 750 "$STATE" "$STATE/hf"
  if [ ! -s "$STATE/agent-token" ]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$STATE/agent-token"
    chown online-dekanat:online-dekanat "$STATE/agent-token"; chmod 600 "$STATE/agent-token"
  fi
fi

if run venv; then
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu
  "$VENV/bin/pip" install -q -r "$REL/deploy/app-v2/requirements-server.txt"
fi

if run model; then
  mkdir -p "$MODEL"
  "$VENV/bin/python" "$REL/deploy/app-v2/fetch_base_model.py" "$REL/deploy/app-v2/base-model-manifest.json" "$MODEL"
  rm -rf "$MODEL/.cache"
  chown -R root:root "$MODEL"; chmod -R a+rX,go-w "$MODEL"
fi

if run service; then
  install -m 644 "$REL/deploy/app-v2/online-dekanat-app.service" /etc/systemd/system/online-dekanat-app.service
  systemctl daemon-reload
  systemctl enable online-dekanat-app
  systemctl restart online-dekanat-app
  for i in $(seq 60); do curl -fsS http://127.0.0.1:18780/api/health && break; sleep 2; done
  echo
fi

if run nginx; then
  SITE=$(grep -Rl "server_name dekanat.karpovprod.ru" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
  LIMITS=$(grep -Rl "zone=dekanat_api" /etc/nginx/conf.d/ /etc/nginx/nginx.conf 2>/dev/null | head -1)
  SITE=$(readlink -f "$SITE"); LIMITS=$(readlink -f "$LIMITS")
  stamp=$(date +%Y%m%d-%H%M%S)
  mkdir -p $OPT/nginx-backup
  cp "$SITE" "$OPT/nginx-backup/site-$stamp.conf"; cp "$LIMITS" "$OPT/nginx-backup/limits-$stamp.conf"
  cp "$REL/deploy/app-v2/nginx-site.conf" "$SITE"
  cp "$REL/deploy/app-v2/nginx-limits.conf" "$LIMITS"
  if nginx -t; then
    systemctl reload nginx
  else
    cp "$OPT/nginx-backup/site-$stamp.conf" "$SITE"; cp "$OPT/nginx-backup/limits-$stamp.conf" "$LIMITS"
    echo "nginx -t failed; previous config restored" >&2; exit 1
  fi
fi

if run switch; then
  # old web-v1 worker is no longer routed to; stop it to free memory (files and unit stay for rollback)
  systemctl disable --now online-dekanat || true
fi
