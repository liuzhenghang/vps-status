import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from db import init_db, get_all_servers, get_server_status_data

templates = Jinja2Templates(directory="templates")


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
async def status_page(request: Request):
    """状态页面"""
    from db import get_status_page_data
    
    data = get_status_page_data()
    
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
    
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "overall_class": overall_class,
            "overall_text": overall_text,
            "servers_html": servers_html
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
