#!/usr/bin/env bash
# ============================================================
# ReturnGuard · openGauss 冷备演练（A25：冷备 + 一致性校验）
# ------------------------------------------------------------
# 冷备（cold backup）：数据库停机后整卷拷贝，保证备份时刻数据完全静止、无写入撕裂。
# 比热备/逻辑导出更简单、恢复最可靠，适合每日低频备份与赛前/赛后归档。
#
# 用法：
#   ./og_cold_backup.sh            # 默认备份到 ./backups/og-<日期>.tar.gz
#   BACKUP_DIR=/data/backups ./og_cold_backup.sh
#
# 演练（drill）步骤（建议赛前至少跑一次，确认可恢复）：
#   1) 执行本脚本生成备份
#   2) 停库 → 记录校验和 → 解压备份到临时目录 → 起库于临时端口 → 跑 /health + 抽样查询
#   3) 对比备份前/后校验和一致即视为演练通过
# ============================================================
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/og-cold-${TS}.tar.gz"

echo "[og-cold-backup] 1/5 停止数据库服务（进入静止态）..."
docker compose -f "${COMPOSE_FILE}" stop "${DB_SERVICE}"

echo "[og-cold-backup] 2/5 计算停机态数据卷校验和（用于恢复比对）..."
# 数据卷名为 compose 中定义的 ogdata；用临时容器读取其内容进行校验
CK_BEFORE="$(docker run --rm -v returnguard_ogdata:/data -w /data alpine:3 sh -c 'find . -type f -exec sha256sum {} \; | sort | sha256sum')"
echo "  停机态校验和: ${CK_BEFORE}"

echo "[og-cold-backup] 3/5 打包数据卷 → ${DEST} ..."
mkdir -p "${BACKUP_DIR}"
docker run --rm -v returnguard_ogdata:/data -v "$(pwd)/${BACKUP_DIR}":/backup alpine:3 \
  sh -c "cd /data && tar czf /backup/og-cold-${TS}.tar.gz ."

echo "[og-cold-backup] 4/5 重启数据库服务..."
docker compose -f "${COMPOSE_FILE}" start "${DB_SERVICE}"

echo "[og-cold-backup] 5/5 完成。备份文件: ${DEST}"
echo "  演练恢复时：解压到新卷 → 起库 → 复算校验和，应与停机态一致（${CK_BEFORE}）。"
