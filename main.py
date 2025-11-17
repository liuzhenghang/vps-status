import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn

from db import init_db, get_all_servers, get_server_status_data


# 后台 ping 任务
async def ping_worker():
    """每分钟 ping 所有服务器"""
    from db import ping_and_record
    while True:
        try:
            await ping_and_record()
        except Exception as e:
            print(f"Ping worker error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    init_db()
    print("数据库初始化完成")
    
    # 启动后台 ping 任务
    task = asyncio.create_task(ping_worker())
    print("后台 ping 任务已启动")
    
    yield
    
    # 关闭时取消任务
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "VPS Status Monitor API"}


@app.post("/api/heartbeat")
async def heartbeat(request: Request):
    """接收客户端心跳上报"""
    from db import record_heartbeat
    
    data = await request.json()
    client_ip = request.client.host if request.client else "unknown"
    
    result = record_heartbeat(
        server_id=data.get("server_id"),
        server_name=data.get("server_name"),
        up_bytes=data.get("up_bytes", 0),
        down_bytes=data.get("down_bytes", 0),
        cpu_load=data.get("cpu_load", 0),
        mem_load=data.get("mem_load", 0),
        client_ip=client_ip,
        raw_data=data
    )
    
    return {"ok": True, "server_id": result["server_id"]}


@app.get("/api/servers")
async def list_servers():
    """列出所有服务器"""
    servers = get_all_servers()
    return {"servers": servers}


@app.get("/status", response_class=HTMLResponse)
async def status_page():
    """状态页面"""
    from db import get_status_page_data
    
    data = get_status_page_data()
    
    html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>VPS 状态监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            padding: 40px 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            font-size: 32px;
            margin-bottom: 10px;
            color: #fff;
        }
        .overall-status {
            font-size: 18px;
            margin-bottom: 40px;
            padding: 15px 20px;
            border-radius: 8px;
            background: #1a1a1a;
        }
        .overall-status.ok { border-left: 4px solid #10b981; }
        .overall-status.warn { border-left: 4px solid #f59e0b; }
        .overall-status.error { border-left: 4px solid #ef4444; }
        
        .server-card {
            background: #1a1a1a;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            border: 1px solid #2a2a2a;
        }
        .server-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .server-info h2 {
            font-size: 20px;
            margin-bottom: 4px;
            color: #fff;
        }
        .server-info .ip {
            color: #888;
            font-size: 14px;
        }
        .health-indicators {
            display: flex;
            gap: 12px;
        }
        .health-badge {
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
        }
        .health-badge.ok {
            background: #10b98133;
            color: #10b981;
        }
        .health-badge.warn {
            background: #f59e0b33;
            color: #f59e0b;
        }
        .health-badge.down {
            background: #ef444433;
            color: #ef4444;
        }
        
        .status-timeline {
            margin-top: 16px;
        }
        .timeline-label {
            font-size: 12px;
            color: #888;
            margin-bottom: 8px;
        }
        .timeline-bar {
            display: flex;
            gap: 2px;
            height: 40px;
            border-radius: 4px;
            overflow: hidden;
        }
        .timeline-slot {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .timeline-slot .ping {
            height: 50%;
            background: #2a2a2a;
        }
        .timeline-slot .heartbeat {
            height: 50%;
            background: #2a2a2a;
        }
        .timeline-slot .ping.ok { background: #10b981; }
        .timeline-slot .ping.warn { background: #f59e0b; }
        .timeline-slot .ping.down { background: #ef4444; }
        .timeline-slot .heartbeat.ok { background: #3b82f6; }
        .timeline-slot .heartbeat.down { background: #6b7280; }
        
        .time-labels {
            display: flex;
            justify-content: space-between;
            margin-top: 6px;
            font-size: 11px;
            color: #666;
        }
        .legend {
            margin-top: 12px;
            display: flex;
            gap: 20px;
            font-size: 12px;
            color: #888;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .legend-color {
            width: 20px;
            height: 10px;
            border-radius: 2px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>VPS 状态监控</h1>
        <div class="overall-status {overall_class}">
            <strong>系统状态：</strong>{overall_text}
        </div>
        
        {servers_html}
    </div>
    
    <script>
        // 每 30 秒自动刷新页面
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>
"""
    
    # 构建整体状态
    if data["overall_status"] == "ok":
        overall_class = "ok"
        overall_text = "所有服务正常运行"
    elif data["overall_status"] == "warn":
        overall_class = "warn"
        overall_text = "部分服务异常"
    else:
        overall_class = "error"
        overall_text = "存在服务宕机"
    
    # 构建服务器卡片
    servers_html_parts = []
    for srv in data["servers"]:
        # 健康状态徽章
        ping_class = "ok" if srv["ping_health"] == "ok" else ("warn" if srv["ping_health"] == "warn" else "down")
        ping_text = "Ping 正常" if srv["ping_health"] == "ok" else ("Ping 警告" if srv["ping_health"] == "warn" else "Ping 宕机")
        
        hb_class = "ok" if srv["heartbeat_health"] == "ok" else "down"
        hb_text = "上报正常" if srv["heartbeat_health"] == "ok" else "上报中断"
        
        # 24小时时间线
        timeline_slots = []
        for slot in srv["timeline"]:
            ping_status = "ok" if slot["ping"] == 1 else ("warn" if slot["ping"] == -1 else "down")
            hb_status = "ok" if slot["heartbeat"] == 1 else "down"
            timeline_slots.append(f'''
                <div class="timeline-slot">
                    <div class="ping {ping_status}"></div>
                    <div class="heartbeat {hb_status}"></div>
                </div>
            ''')
        
        servers_html_parts.append(f'''
        <div class="server-card">
            <div class="server-header">
                <div class="server-info">
                    <h2>{srv["name"]}</h2>
                    <div class="ip">{srv["ip"]}</div>
                </div>
                <div class="health-indicators">
                    <div class="health-badge {ping_class}">{ping_text}</div>
                    <div class="health-badge {hb_class}">{hb_text}</div>
                </div>
            </div>
            
            <div class="status-timeline">
                <div class="timeline-label">过去 24 小时状态</div>
                <div class="timeline-bar">
                    {''.join(timeline_slots)}
                </div>
                <div class="time-labels">
                    <span>24h 前</span>
                    <span>现在</span>
                </div>
                <div class="legend">
                    <div class="legend-item">
                        <div class="legend-color" style="background: #10b981;"></div>
                        <span>Ping 正常</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #3b82f6;"></div>
                        <span>上报正常</span>
                    </div>
                    <div class="legend-item">
                        <div class="legend-color" style="background: #6b7280;"></div>
                        <span>无数据</span>
                    </div>
                </div>
            </div>
        </div>
        ''')
    
    servers_html = '\n'.join(servers_html_parts) if servers_html_parts else '<p style="color: #888;">暂无服务器数据</p>'
    
    html = html.format(
        overall_class=overall_class,
        overall_text=overall_text,
        servers_html=servers_html
    )
    
    return html


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
