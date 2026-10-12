#!/usr/bin/env bash
# ============================================================================
# 念家鲜饺供应链系统 —— MySQL 每日全量逻辑备份
# 目标环境：单机 Docker Compose（deploy/docker-compose.prod.yml），MySQL 不暴露宿主端口
# 使用：sudo /opt/nianjia-xianjiao/deploy/backup.sh   （首次需 chmod +x deploy/backup.sh）
# 依赖：docker compose 可用；deploy/.env 已填 MYSQL_ROOT_PASSWORD / MYSQL_DATABASE
# ----------------------------------------------------------------------------
# crontab 挂法（每日 03:00，避开白天业务高峰）：
#   sudo crontab -e
#   0 3 * * * /opt/nianjia-xianjiao/deploy/backup.sh
# 脚本自身把输出追加到 /var/log/mysql-backup.log，无需再重定向；
# 若偏好由 cron 管理日志，也可写成：
#   0 3 * * * /opt/nianjia-xianjiao/deploy/backup.sh >> /var/log/mysql-backup.log 2>&1
# 日志轮转（避免日志无限增长）：
#   sudo tee /etc/logrotate.d/mysql-backup >/dev/null <<'EOF'
#   /var/log/mysql-backup.log { weekly rotate 8 missingok notifempty compress }
#   EOF
# ============================================================================
set -euo pipefail

# 备份文件仅属主可读：dump 内含全量业务数据，敏感级别等同数据库本身
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.prod.yml"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/mysql}"   # 备份落盘目录（可改到数据盘）
RETENTION_DAYS="${RETENTION_DAYS:-7}"            # 本地保留天数，超期自动删除
LOG_FILE="${LOG_FILE:-/var/log/mysql-backup.log}"
STAMP="$(date +%Y%m%d_%H%M%S)"                    # 文件名带日期+时间，便于排序与人工识别

# 日志：优先写 LOG_FILE；不可写时退回 stderr，绝不静默吞掉失败信息
if : >>"${LOG_FILE}" 2>/dev/null; then exec >>"${LOG_FILE}" 2>&1; else echo "警告：${LOG_FILE} 不可写，日志输出到 stderr" >&2; fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# 失败告警：先落日志；配置了 ALERT_WEBHOOK（企业微信/钉钉机器人）时再推送一条
alert() {
  local msg="$1"
  log "ALERT: ${msg}"
  if [[ -n "${ALERT_WEBHOOK:-}" ]]; then
    curl -fsS -m 10 -X POST -H 'Content-Type: application/json' \
      -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[MySQL备份失败] ${msg}\"}}" \
      "${ALERT_WEBHOOK}" >/dev/null 2>&1 || log "ALERT: webhook 推送失败（本地日志已记录）"
  fi
}
trap 'alert "备份失败（脚本第 ${LINENO} 行），请人工介入检查"; exit 1' ERR

# 从 .env 读取所需变量（不整份导入环境）
# 注意：值中若含 # 会被 .env 规则截断，密码请使用不含 # 的随机串
env_val() { grep -E "^$1=" "${ENV_FILE}" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

[[ -f "${ENV_FILE}" ]] || { alert "找不到 ${ENV_FILE}，请先按 README-deploy.md 配置"; exit 1; }
MYSQL_ROOT_PASSWORD="$(env_val MYSQL_ROOT_PASSWORD)"
MYSQL_DATABASE="$(env_val MYSQL_DATABASE)"
[[ -n "${MYSQL_ROOT_PASSWORD}" && -n "${MYSQL_DATABASE}" ]] || { alert ".env 中缺少 MYSQL_ROOT_PASSWORD 或 MYSQL_DATABASE"; exit 1; }

mkdir -p "${BACKUP_DIR}"
cd "${SCRIPT_DIR}"   # 切到 deploy/，保证 docker compose 能加载同目录 .env

BACKUP_FILE="${BACKUP_DIR}/${MYSQL_DATABASE}_${STAMP}.sql.gz"
log "开始备份 ${MYSQL_DATABASE} -> ${BACKUP_FILE}"

# --single-transaction：InnoDB 一致性快照且不锁表，备份期间业务可继续写入
# --quick：大表边读边发，避免 mysqldump 端内存暴涨（1.3GB 机器关键）
# MYSQL_PWD 传密码：不出现在 ps 命令行参数里，比 -p<password> 安全
docker compose -f "${COMPOSE_FILE}" exec -T \
  -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql \
  mysqldump --single-transaction --quick --routines --events --triggers \
  --default-character-set=utf8mb4 -uroot "${MYSQL_DATABASE}" \
  | gzip -9 > "${BACKUP_FILE}.tmp"

# 先做 gzip 完整性校验，再原子改名：避免半截文件被当成可用备份
gzip -t "${BACKUP_FILE}.tmp"
mv "${BACKUP_FILE}.tmp" "${BACKUP_FILE}"
log "备份完成：${BACKUP_FILE}（$(du -h "${BACKUP_FILE}" | cut -f1)）"

# 保留策略：只删本目录下匹配本库命名规则、且超过保留天数的文件
DELETED="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${MYSQL_DATABASE}_*.sql.gz" -mtime +"${RETENTION_DAYS}" -print -delete | wc -l)"
log "清理超期备份：删除 ${DELETED} 个（保留 ${RETENTION_DAYS} 天）"
log "备份任务结束"
