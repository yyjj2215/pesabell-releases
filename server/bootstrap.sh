#!/bin/bash
# PesaBell server bootstrap. Runs once, as root, when a new server is created
# (the server's startup script / cloud-init user-data only downloads and runs this file).
#
# What it does:
#   1. basics: time zone, swap, security updates, firewall (ssh, http, https, mqtt, mqtts)
#   2. makes a "deploy key" for the private repository github.com/yyjj2215/pesabell-server and
#      shows it on http://<server-ip>/ until it has been added to that repository
#   3. installs pesabell-sync, which every 30 seconds pulls new commits from that repository,
#      runs its deploy/install.sh, and pushes the server's status and logs to its "status" branch
#
# Nothing secret is in this file. It is safe to run again.
set -euxo pipefail
exec > >(tee -a /var/log/pesabell-bootstrap.log) 2>&1

BASE=/opt/pesabell
KEY=/root/.ssh/pesabell_deploy
export DEBIAN_FRONTEND=noninteractive
APT="apt-get -y -q -o DPkg::Lock::Timeout=600"

mkdir -p "$BASE"
timedatectl set-timezone Africa/Nairobi || true

# Swap, so a memory spike slows the server down instead of killing it.
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

$APT update
$APT install git curl ca-certificates ufw unattended-upgrades python3 openssh-client
systemctl enable --now unattended-upgrades || true

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 1883/tcp
ufw allow 8883/tcp
ufw --force enable

# Deploy key, and GitHub's real host keys (taken from GitHub's API over HTTPS, not trusted on first use).
install -d -m 700 /root/.ssh
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C "pesabell-server" -f "$KEY"
curl -fsSL https://api.github.com/meta | python3 -c '
import json, sys
for k in json.load(sys.stdin)["ssh_keys"]:
    print("github.com " + k)' > /root/.ssh/known_hosts_github
cat > /root/.ssh/config <<EOF
Host github.com
  User git
  IdentityFile $KEY
  IdentitiesOnly yes
  UserKnownHostsFile /root/.ssh/known_hosts_github
  StrictHostKeyChecking yes
EOF
chmod 600 /root/.ssh/config

# Setup page on port 80 (pesabell-sync rewrites it as setup progresses and stops it before deploying).
mkdir -p "$BASE/keypage"
cat > "$BASE/keypage.sh" <<'EOF'
#!/bin/bash
# keypage.sh <state>: writes the setup page. state = need-key | need-write | waiting
BASE=/opt/pesabell
OWNER_REPO=yyjj2215/pesabell-server
PUB=$(cat /root/.ssh/pesabell_deploy.pub)
case "$1" in
  need-key)
    TITLE="PesaBell 服务器已开机 ✓ — 还差最后一步"
    BODY="<p>把下面这一行「部署公钥」加到 GitHub，服务器就能自动取代码：</p>
<ol><li>打开 <a href=\"https://github.com/$OWNER_REPO/settings/keys/new\" target=\"_blank\">github.com/$OWNER_REPO/settings/keys/new</a></li>
<li>Title 填 <b>pesabell-1</b>，Key 粘贴下面整行，<b>勾选 Allow write access</b>，点 Add key。</li></ol>
<textarea readonly rows=\"3\" style=\"width:100%;font-size:14px\" onclick=\"this.select()\">$PUB</textarea>
<p>加好后一分钟内，这个页面会变成「已连接」。</p>" ;;
  need-write)
    TITLE="公钥已生效，但没有写入权限"
    BODY="<p>服务器能读代码，但不能回传运行状态。请在 <a href=\"https://github.com/$OWNER_REPO/settings/keys\" target=\"_blank\">github.com/$OWNER_REPO/settings/keys</a> 删掉 pesabell-1 这个 key，再用下面同一行重新添加，这次<b>勾选 Allow write access</b>。</p>
<textarea readonly rows=\"3\" style=\"width:100%;font-size:14px\" onclick=\"this.select()\">$PUB</textarea>" ;;
  *)
    TITLE="已连接 GitHub ✓"
    BODY="<p>服务器已经能自动取代码了。Claude 推送服务器程序后，这里会换成 PesaBell 的页面。</p>" ;;
esac
cat > "$BASE/keypage/index.html" <<HTML
<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>PesaBell server</title>
<body style="font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6">
<h2>$TITLE</h2>$BODY</body>
HTML
EOF
chmod +x "$BASE/keypage.sh"
[ -d "$BASE/app/.git" ] || "$BASE/keypage.sh" need-key

cat > /etc/systemd/system/pesabell-keypage.service <<EOF
[Unit]
Description=PesaBell setup page (until the server code is deployed)
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m http.server 80 --directory $BASE/keypage
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# pesabell-sync: pull, deploy, report.
cat > /usr/local/bin/pesabell-sync <<'EOF'
#!/bin/bash
# Keeps this server in step with the private repository github.com/yyjj2215/pesabell-server:
#   - a new commit on main: check it out, run deploy/install.sh (once per commit), report
#   - a new commit on the "ping" branch: report now
#   - otherwise: report every 15 minutes
# A report force-pushes one commit with the server's state and recent logs to the "status" branch.
set -u
BASE=${PESABELL_BASE:-/opt/pesabell}
APP=$BASE/app
REPO=${PESABELL_REPO:-git@github.com:yyjj2215/pesabell-server.git}
LOG=${PESABELL_LOG:-/var/log/pesabell-sync.log}
REPORT_EVERY=${PESABELL_REPORT_EVERY:-900}

exec 9>"$BASE/sync.lock"
flock -n 9 || exit 0
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

report() {
  local t ok=0
  t=$(mktemp -d)
  {
    echo "host:     $(hostname)"
    echo "time:     $(date -Is)"
    echo "deployed: $(cat "$BASE/deployed" 2>/dev/null)"
    echo "failed:   $(cat "$BASE/failed" 2>/dev/null)"
    echo
    uptime
    echo
    free -m
    echo
    df -h /
  } > "$t/server.txt" 2>&1
  tail -n 400 "$LOG" > "$t/sync.log" 2>/dev/null
  cp "$BASE/deploy.log" "$t/deploy.log" 2>/dev/null
  if [ -x "$APP/deploy/status.sh" ]; then timeout 120 "$APP/deploy/status.sh" "$t" > "$t/status.txt" 2>&1; fi
  (
    cd "$t" && git init -q -b status && git add -A &&
      git -c user.name=pesabell-server -c user.email=server@pesabell.com commit -q -m "status $(date -Is)" &&
      git push -q -f "$REPO" HEAD:refs/heads/status
  ) >> "$LOG" 2>&1 || ok=1
  rm -rf "$t"
  date +%s > "$BASE/last-report"
  [ $ok = 0 ] || log "status push failed"
  return $ok
}

if [ ! -d "$APP/.git" ]; then
  git ls-remote "$REPO" > /dev/null 2> "$BASE/ls-remote.err" || exit 0   # deploy key not added yet
  rm -f "$BASE/ls-remote.err"
  git clone -q "$REPO" "$APP" >> "$LOG" 2>&1 || { log "clone failed"; exit 0; }
  log "deploy key works, repository cloned"
  [ -x "$BASE/keypage.sh" ] && "$BASE/keypage.sh" waiting
fi
cd "$APP" || exit 0
git fetch -q --prune origin >> "$LOG" 2>&1 || { log "fetch failed"; exit 0; }
target=$(git rev-parse -q --verify refs/remotes/origin/main) || exit 0   # nothing on main yet

# The first report doubles as the check that the key may push. Without that we would deploy blind.
if [ ! -f "$BASE/write-ok" ]; then
  if report; then
    touch "$BASE/write-ok"
    log "deploy key can push status"
  else
    [ -x "$BASE/keypage.sh" ] && "$BASE/keypage.sh" need-write
    exit 0
  fi
fi

if [ "$target" != "$(cat "$BASE/deployed" 2>/dev/null)" ] && [ "$target" != "$(cat "$BASE/failed" 2>/dev/null)" ]; then
  git checkout -q -f -B main "$target" && git clean -q -f -d
  log "deploying ${target:0:7}: $(git log -1 --format=%s)"
  if [ -x deploy/install.sh ]; then
    systemctl disable --now pesabell-keypage > /dev/null 2>&1
    if timeout 25m deploy/install.sh > "$BASE/deploy.log" 2>&1; then
      echo "$target" > "$BASE/deployed"
      rm -f "$BASE/failed"
      log "deployed ${target:0:7}"
    else
      echo "$target" > "$BASE/failed"
      log "deploy of ${target:0:7} FAILED, see deploy.log"
    fi
  else
    echo "$target" > "$BASE/deployed"
    log "no deploy/install.sh in ${target:0:7}, nothing to run"
  fi
  report
  exit 0
fi

ping=$(git rev-parse -q --verify refs/remotes/origin/ping)
if [ -n "$ping" ] && [ "$ping" != "$(cat "$BASE/ping-seen" 2>/dev/null)" ]; then
  echo "$ping" > "$BASE/ping-seen"
  log "report requested"
  report
  exit 0
fi

last=$(cat "$BASE/last-report" 2>/dev/null || echo 0)
if [ $(( $(date +%s) - last )) -ge "$REPORT_EVERY" ]; then report; fi
exit 0
EOF
chmod +x /usr/local/bin/pesabell-sync

cat > /etc/systemd/system/pesabell-sync.service <<'EOF'
[Unit]
Description=PesaBell: pull github.com/yyjj2215/pesabell-server, deploy, report status
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=HOME=/root
ExecStart=/usr/local/bin/pesabell-sync
TimeoutStartSec=30min
EOF

cat > /etc/systemd/system/pesabell-sync.timer <<'EOF'
[Unit]
Description=Run pesabell-sync every 30 seconds

[Timer]
OnBootSec=20s
OnUnitInactiveSec=30s
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
if [ ! -f "$BASE/deployed" ]; then systemctl enable --now pesabell-keypage; fi
systemctl enable --now pesabell-sync.timer
echo "PesaBell bootstrap done"
