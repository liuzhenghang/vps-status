#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-vps-agent-builder}"
OUTPUT="${OUTPUT:-agent-linux-x64}"

echo "使用镜像名: ${IMAGE_NAME}"
echo "输出文件: ${OUTPUT}"

echo "==> 构建 Docker 镜像（用于打包 agent）..."
docker build -f Dockerfile-agent -t "${IMAGE_NAME}" .

echo "==> 创建临时容器..."
CID="$(docker create "${IMAGE_NAME}")"

echo "==> 拷贝编译好的二进制到本地..."
docker cp "${CID}":/app/agent "./${OUTPUT}"

echo "==> 清理临时容器..."
docker rm "${CID}" >/dev/null

chmod +x "./${OUTPUT}" || true

echo "完成，生成文件: ${OUTPUT}"


