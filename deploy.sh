#!/bin/bash
# 服务器端一键更新：拉取 GitHub 最新代码并重建服务
# 用法：bash deploy.sh
set -e
cd "$(dirname "$0")"

echo "==> 拉取最新代码"
git pull origin main

echo "==> 重建并启动服务（含自动数据库迁移）"
docker compose -f docker-compose.prod.yml up -d --build

echo "==> 当前容器状态"
docker compose -f docker-compose.prod.yml ps
echo "==> 完成！浏览器访问 http://服务器IP:${APP_PORT:-8080}"
