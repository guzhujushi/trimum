#!/usr/bin/env bash
# trimum Ubuntu one-shot installer.
#
# Installs or updates the trimum Core daemon under /opt/trimum, creates the
# system service account, installs the Python package into a virtualenv,
# installs config/policy files, and enables the systemd service.
#
# Usage:
#   sudo bash scripts/install.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths and defaults
# ---------------------------------------------------------------------------
APP_DIR="${TRIMUM_APP_DIR:-/opt/trimum}"
BIN_DIR="${APP_DIR}/bin"
CONFIG_DIR="${APP_DIR}/config"
VENV_DIR="${APP_DIR}/.venv"
LOG_DIR="${TRIMUM_LOG_DIR:-/var/log/trimum}"
DATA_DIR="${TRIMUM_DATA_DIR:-/var/lib/trimum}"
RUN_DIR="${TRIMUM_RUN_DIR:-/run/trimum}"
SERVICE_NAME="trmd"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
REPO_URL="${TRIMUM_REPO_URL:-https://github.com/guzhujushi/trimum.git}"
PYTHON_BIN=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${BLUE}[trimum]${NC} $*"; }
success() { echo -e "${GREEN}[trimum]${NC} $*"; }
warn()    { echo -e "${YELLOW}[warning]${NC} $*" >&2; }
die()     { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

version_at_least() {
    # Compares dotted versions, for example: 3.12 >= 3.12 -> true.
    awk -v current="$1" -v required="$2" 'BEGIN {
        split(current, c, ".")
        split(required, r, ".")
        for (i = 1; i <= 3; i++) {
            if (c[i] + 0 > r[i] + 0) exit 0
            if (c[i] + 0 < r[i] + 0) exit 1
        }
        exit 0
    }'
}

find_python() {
    # Prefer a dedicated python3.12+ binary, then fall back to python3.
    local candidate version
    for candidate in python3.12 python3.13 python3.14 python3.15 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
            if [[ -n "$version" ]] && version_at_least "$version" "3.12"; then
                PYTHON_BIN="$candidate"
                return 0
            fi
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    die "This installer must run as root. Try: sudo bash scripts/install.sh"
fi

command -v apt-get >/dev/null 2>&1 || die "apt-get was not found; this installer targets Ubuntu/Debian."
command -v systemctl >/dev/null 2>&1 || die "systemctl was not found; this installer requires systemd."

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# 1. Install system dependencies
# ---------------------------------------------------------------------------
info "[1/9] Installing system build dependencies"
apt-get update
apt-get install -y \
    ca-certificates \
    curl \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential

# ---------------------------------------------------------------------------
# 2. Locate or install Python 3.12+
# ---------------------------------------------------------------------------
info "[2/9] Locating Python 3.12+"
if ! find_python; then
    warn "No Python 3.12+ runtime was found; installing python3.12 now"
    apt-get install -y python3.12 python3.12-venv python3.12-dev || \
        die "python3.12 is not available in apt. On older Ubuntu releases, add the deadsnakes PPA and retry."
    find_python || die "python3.12 was installed but is still unavailable."
fi
info "Using Python: ${PYTHON_BIN} ($(${PYTHON_BIN} --version 2>&1))"

# ---------------------------------------------------------------------------
# 3. Prepare the source tree
# ---------------------------------------------------------------------------
info "[3/9] Preparing the trimum source tree"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${SOURCE_ROOT}/pyproject.toml" ]]; then
    SOURCE_DIR="${SOURCE_ROOT}"
    info "Using existing source tree: ${SOURCE_DIR}"
else
    info "No local source tree detected; using ${APP_DIR}"
    if [[ -d "${APP_DIR}/.git" ]]; then
        info "Updating existing repository at ${APP_DIR}"
        git -C "${APP_DIR}" pull --ff-only
    else
        if [[ -d "${APP_DIR}" ]] && [[ -n "$(ls -A "${APP_DIR}" 2>/dev/null)" ]]; then
            die "${APP_DIR} is not empty and is not a git repository; refusing to overwrite it."
        fi
        mkdir -p "${APP_DIR}"
        info "Cloning ${REPO_URL}"
        git clone --depth 1 "${REPO_URL}" "${APP_DIR}"
    fi
    SOURCE_DIR="${APP_DIR}"
fi

# ---------------------------------------------------------------------------
# 4. Create directory layout
# ---------------------------------------------------------------------------
info "[4/9] Creating trimum directories"
install -d -m 0755 "${BIN_DIR}" "${CONFIG_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${RUN_DIR}"

# ---------------------------------------------------------------------------
# 5. Create the service account
# ---------------------------------------------------------------------------
info "[5/9] Creating the trimum service account"
if id -u trimum >/dev/null 2>&1; then
    info "User trimum already exists; keeping the existing account"
else
    useradd -r -s /usr/sbin/nologin trimum
    info "Created system user trimum"
fi

# /run is a tmpfs and is cleared on reboot; make systemd recreate it for us.
cat > /etc/tmpfiles.d/trimum.conf <<'EOF'
d /run/trimum 0750 trimum trimum - -
EOF
if command -v systemd-tmpfiles >/dev/null 2>&1; then
    systemd-tmpfiles --create /etc/tmpfiles.d/trimum.conf
else
    warn "systemd-tmpfiles was not found; ${RUN_DIR} may need to be recreated after reboot"
fi

# ---------------------------------------------------------------------------
# 6. Create the virtualenv and install the package
# ---------------------------------------------------------------------------
info "[6/9] Installing trimum-core in a virtualenv"
"${PYTHON_BIN}" -m venv --clear "${VENV_DIR}" || {
    warn "Virtualenv creation failed; installing the matching venv package"
    local_python_version="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    apt-get install -y "python${local_python_version}-venv"
    "${PYTHON_BIN}" -m venv --clear "${VENV_DIR}"
}
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -e "${SOURCE_DIR}"

# ---------------------------------------------------------------------------
# 7. Install command wrappers
# ---------------------------------------------------------------------------
info "[7/9] Installing trmd and trm wrappers"
cat > "${BIN_DIR}/trmd" <<EOF
#!/usr/bin/env bash
# trimum Core daemon launcher, installed by scripts/install.sh.
set -euo pipefail
exec "${VENV_DIR}/bin/python" -m trimum_core.main "\$@"
EOF

cat > "${BIN_DIR}/trm" <<EOF
#!/usr/bin/env bash
# trm CLI launcher, installed by scripts/install.sh.
set -euo pipefail
exec "${VENV_DIR}/bin/python" -m trimum_core.main "\$@"
EOF

chmod 0755 "${BIN_DIR}/trmd" "${BIN_DIR}/trm"

# ---------------------------------------------------------------------------
# 8. Install config, policy, and the systemd unit
# ---------------------------------------------------------------------------
info "[8/9] Installing config and systemd unit"

cat > "${CONFIG_DIR}/config.yaml" <<'EOF'
# trimum Core — Ubuntu default config
# Installed by scripts/install.sh

core:
  host: "127.0.0.1"
  port: 8321
  socket_path: "/run/trimum/trimum.sock"
  workers: 1

logging:
  level: info
  file: "/var/log/trimum/trimum.log"
  format: json

context:
  db_path: "/var/lib/trimum/context.db"

policy:
  path: "/opt/trimum/config/policy.yaml"

agent_manager:
  max_agents: 10
  health_check_interval: 30
EOF

if [[ -f "${SOURCE_DIR}/config/policy.yaml" ]]; then
    install -m 0644 "${SOURCE_DIR}/config/policy.yaml" "${CONFIG_DIR}/policy.yaml"
else
    cat > "${CONFIG_DIR}/policy.yaml" <<'EOF'
# Fallback policy installed by scripts/install.sh.
rules:
  - pattern: "ls|cat|head|tail|find|grep|df|du|ps|pwd|whoami|echo|which|uname|free|uptime|date|id|who"
    risk: low
    action: auto
  - pattern: "rm|chmod|chown|mv|cp|mkdir|touch|kill|pkill|systemctl|apt|pip|npm install"
    risk: medium
    action: confirm
  - pattern: "rm -rf /|chmod -R 777 /|dd if=/dev|> /dev/sda|:(){ :|:& };:|mkfs|format"
    risk: critical
    action: deny
default_action: confirm
default_risk: medium
EOF
fi

if [[ -f "${SOURCE_DIR}/scripts/trmd.service" ]]; then
    install -m 0644 "${SOURCE_DIR}/scripts/trmd.service" "${SERVICE_FILE}"
else
    die "scripts/trmd.service was not found in ${SOURCE_DIR}; cannot install the systemd unit."
fi

# ---------------------------------------------------------------------------
# 9. Set ownership and start the service
# ---------------------------------------------------------------------------
info "[9/9] Setting ownership and starting ${SERVICE_NAME}"
chown -R trimum:trimum "${APP_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${RUN_DIR}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}" >/dev/null

if systemctl start "${SERVICE_NAME}"; then
    success "✅ trimum installed"
    systemctl status "${SERVICE_NAME}" --no-pager || true
else
    warn "trimum was installed, but the service failed to start."
    systemctl status "${SERVICE_NAME}" --no-pager || true
    exit 1
fi

echo
info "Config: ${CONFIG_DIR}/config.yaml"
info "Data:   ${DATA_DIR}"
info "Logs:   journalctl -u ${SERVICE_NAME} -f"
