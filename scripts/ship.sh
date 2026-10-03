#!/usr/bin/env bash
# Echo 快速提交脚本：暂存全部改动 → 提交 → 推送到 Gitee origin/master。
# 用法：
#   bash scripts/ship.sh "feat(ui): 一句话说明"
#   bash scripts/ship.sh              # 不带参数用时间戳当消息
set -euo pipefail
cd "$(dirname "$0")/.."

msg="${1:-$(date '+%Y-%m-%d %H:%M') 更新}"

git add -A
if git commit -m "$msg"; then
    git push origin master
else
    echo "没有可提交的改动，跳过。"
fi
