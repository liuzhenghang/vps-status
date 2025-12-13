# VPS 状态监控系统

一个轻量级的 VPS 服务器监控系统，支持实时监控服务器状态、CPU/内存使用率、网络流量，并提供美观的 Web 界面。

## 功能特性

- 🖥️ **多服务器监控**：支持同时监控多个 VPS 服务器
- 📊 **实时指标采集**：CPU、内存、网络流量实时监控
- 🔄 **心跳上报机制**：客户端定期上报服务器状态
- 🌐 **Web 界面**：美观的暗色主题状态展示页面
- 📈 **历史数据追踪**：24小时状态时间线和资源使用趋势图
- 🐳 **Docker 部署**：支持容器化部署和运行
- 🔧 **自动注册**：客户端自动注册服务器，无需手动配置
- 📱 **响应式设计**：适配不同设备屏幕

## 系统架构

### 服务端 (Server)
- 基于 FastAPI 构建的 REST API
- SQLite 数据库存储监控数据
- 后台任务自动 Ping 检查服务器连通性
- Web 界面实时展示服务器状态

### 客户端 (Agent)
- Python 脚本，采集本地系统指标
- 支持周期性上报和单次上报模式
- 自动注册机制，获取服务器 ID
- 轻量级，无额外依赖（仅需 Python 3.6+）

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 克隆项目
git clone <repository-url>
cd vps-status

# 使用 Docker Compose 启动服务端
docker-compose up -d

# 服务将在 http://localhost:8000 运行
```

### 方式二：手动部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务端
python main.py

# 服务将在 http://localhost:0.0.0.0:8000 运行
```

### 客户端部署

在要监控的 VPS 上安装客户端：

```bash
# 方法1：直接运行 Python 脚本（需要安装依赖）
pip install psutil requests

# 注册服务器并获取 ID
python agent.py --server-url http://your-server:8000 --server-name "My VPS" --register

# 启动监控客户端
python agent.py --server-url http://your-server:8000 --server-id YOUR_SERVER_ID

# 方法2：使用编译后的二进制（无需安装依赖）
# 构建二进制（在开发环境）
./build-agent.sh

# 然后将生成的 agent-linux-x64 上传到 VPS 并运行
./agent-linux-x64 --server-url http://your-server:8000 --server-id YOUR_SERVER_ID
```

## API 接口

### 服务端 API

- `GET /` - API 状态检查
- `POST /api/register` - 注册新服务器
- `POST /api/heartbeat` - 接收客户端心跳上报
- `GET /api/servers` - 获取所有服务器列表
- `GET /status` - Web 状态监控页面

### 客户端命令行参数

```bash
python agent.py [OPTIONS]

Options:
  --server-url TEXT     服务端地址 (必需)
  --server-id TEXT      服务器ID (推荐使用)
  --server-name TEXT    服务器名称 (与 --server-id 二选一)
  --interval INTEGER    上报间隔(秒)，默认 60
  --once                单次上报后退出
  --register            仅注册并打印服务器ID
  --help                显示帮助信息
```

## 监控指标

- **CPU 使用率**：系统 CPU 负载百分比
- **内存使用率**：系统内存使用百分比
- **网络流量**：累计上行/下行字节数
- **连通性检查**：通过 Ping 检测服务器响应
- **心跳状态**：客户端定期上报状态

## 状态定义

### 服务器健康状态
- **正常 (OK)**：Ping 正常，心跳正常
- **警告 (WARN)**：Ping 延迟较高
- **异常 (DOWN)**：Ping 失败或心跳中断

### 时间线颜色说明
- 🟢 **绿色**：Ping 正常
- 🟡 **黄色**：Ping 警告
- 🔴 **红色**：Ping 失败
- 🔵 **蓝色**：心跳正常
- ⚫ **灰色**：无数据

## 部署建议

### 生产环境配置

1. **数据库持久化**：使用 Docker volumes 或外部数据库
2. **反向代理**：配置 Nginx 反向代理和 SSL 证书
3. **监控告警**：集成外部监控系统（如 Prometheus + Grafana）
4. **安全配置**：设置防火墙，限制 API 访问

### 示例 Nginx 配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## 故障排除

### 常见问题

1. **客户端无法连接服务端**
   - 检查网络连通性和防火墙设置
   - 确认服务端 URL 格式正确

2. **数据不显示在 Web 界面**
   - 检查客户端是否正常上报
   - 查看服务端日志确认数据接收情况

3. **Ping 检查失败**
   - 确认服务器支持 ICMP Ping
   - 检查网络配置和防火墙规则

### 日志查看

```bash
# Docker 部署查看日志
docker-compose logs -f vps-status

# 手动部署查看日志
python main.py  # 日志会直接输出到控制台
```

## 开发说明

### 项目结构

```
vps-status/
├── main.py          # 服务端主程序
├── agent.py         # 客户端程序
├── db.py            # 数据库操作
├── requirements.txt # Python 依赖
├── Dockerfile       # 服务端容器配置
├── Dockerfile-agent # 客户端构建配置
├── build-agent.sh   # 客户端编译脚本
├── docker-compose.yml
├── templates/
│   └── status.html  # Web 界面模板
└── data/
    └── status.db    # SQLite 数据库
```

### 自定义开发

- 修改 `agent.py` 添加更多监控指标
- 自定义 `status.html` 调整界面样式
- 扩展 API 接口添加更多功能
- 集成外部存储或消息推送

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
