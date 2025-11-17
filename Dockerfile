FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（ping 命令需要 iputils-ping）
RUN apt-get update && \
    apt-get install -y --no-install-recommends iputils-ping && \
    rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY main.py .
COPY db.py .

# 创建数据目录
RUN mkdir -p /app/data

# 环境变量
ENV DB_PATH=/app/data/status.db
ENV PORT=8000

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

