import sqlite3
import time
import json
import threading
from datetime import datetime, timedelta
import subprocess
import re
import os


# 雪花 ID 生成器（简化版）
class SnowflakeIdGenerator:
    def __init__(self, worker_id=1):
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()
        # 2024-01-01 00:00:00 作为起始时间
        self.epoch = 1704067200000
    
    def _current_millis(self):
        return int(time.time() * 1000)
    
    def next_id(self):
        with self.lock:
            timestamp = self._current_millis()
            
            if timestamp < self.last_timestamp:
                raise Exception("时钟回拨")
            
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 4095
                if self.sequence == 0:
                    # 同一毫秒内序列号用完，等待下一毫秒
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_millis()
            else:
                self.sequence = 0
            
            self.last_timestamp = timestamp
            
            # 组装 ID: 42位时间戳 + 10位机器ID + 12位序列号
            snowflake_id = ((timestamp - self.epoch) << 22) | (self.worker_id << 12) | self.sequence
            return str(snowflake_id)


# 全局 ID 生成器
id_gen = SnowflakeIdGenerator()


# 数据库连接
DB_PATH = os.getenv("DB_PATH", "./data/status.db")


def get_db():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # servers 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ip TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            remark TEXT
        )
    """)
    
    # ping_status 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ping_status (
            id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            is_online INTEGER NOT NULL,
            latency_ms REAL,
            FOREIGN KEY (server_id) REFERENCES servers(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ping_server_ts ON ping_status(server_id, ts)")
    
    # heartbeat_status 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS heartbeat_status (
            id TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            ts INTEGER NOT NULL,
            up_bytes INTEGER,
            down_bytes INTEGER,
            cpu_load REAL,
            mem_load REAL,
            ip TEXT,
            raw_json TEXT,
            FOREIGN KEY (server_id) REFERENCES servers(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_heartbeat_server_ts ON heartbeat_status(server_id, ts)")
    
    conn.commit()
    conn.close()


def get_or_create_server(server_id=None, server_name=None, ip=None):
    """获取或创建服务器记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = int(time.time())
    
    # 如果提供了 server_id，直接查询
    if server_id:
        cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)
    
    # 如果提供了 server_name，按名称查询
    if server_name:
        cursor.execute("SELECT * FROM servers WHERE name = ?", (server_name,))
        row = cursor.fetchone()
        if row:
            # 更新 IP 和时间
            if ip:
                cursor.execute(
                    "UPDATE servers SET ip = ?, updated_at = ? WHERE id = ?",
                    (ip, now, row["id"])
                )
                conn.commit()
            conn.close()
            return dict(row)
        
        # 不存在则创建
        new_id = id_gen.next_id()
        cursor.execute(
            "INSERT INTO servers (id, name, ip, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (new_id, server_name, ip or "unknown", now, now)
        )
        conn.commit()
        
        cursor.execute("SELECT * FROM servers WHERE id = ?", (new_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row)
    
    conn.close()
    return None


def get_all_servers():
    """获取所有服务器"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM servers ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def record_heartbeat(server_id=None, server_name=None, up_bytes=0, down_bytes=0, 
                     cpu_load=0, mem_load=0, client_ip=None, raw_data=None):
    """记录心跳数据"""
    # 获取或创建服务器
    server = get_or_create_server(server_id=server_id, server_name=server_name, ip=client_ip)
    if not server:
        raise ValueError("无法确定服务器")
    
    conn = get_db()
    cursor = conn.cursor()
    
    now = int(time.time())
    hb_id = id_gen.next_id()
    
    cursor.execute("""
        INSERT INTO heartbeat_status 
        (id, server_id, ts, up_bytes, down_bytes, cpu_load, mem_load, ip, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (hb_id, server["id"], now, up_bytes, down_bytes, cpu_load, mem_load, 
          client_ip, json.dumps(raw_data) if raw_data else None))
    
    conn.commit()
    conn.close()
    
    return {"server_id": server["id"], "heartbeat_id": hb_id}


async def ping_and_record():
    """ping 所有服务器并记录结果"""
    servers = get_all_servers()
    if not servers:
        return
    
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    
    for server in servers:
        try:
            # 执行 ping 命令
            # Windows 下用 -n 1 -w 1000，Linux 下用 -c 1 -W 1
            is_windows = os.name == 'nt'
            if is_windows:
                cmd = ["ping", "-n", "1", "-w", "1000", server["ip"]]
            else:
                cmd = ["ping", "-c", "1", "-W", "1", server["ip"]]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            
            is_online = 0
            latency_ms = None
            
            if result.returncode == 0:
                is_online = 1
                # 尝试解析延迟时间
                output = result.stdout
                if is_windows:
                    # Windows: 时间=XXms 或 time=XXms
                    match = re.search(r'[时间time]=?(\d+)ms', output, re.IGNORECASE)
                else:
                    # Linux: time=XX.X ms
                    match = re.search(r'time[=<]([0-9.]+)\s*ms', output)
                
                if match:
                    latency_ms = float(match.group(1))
            
            ping_id = id_gen.next_id()
            cursor.execute("""
                INSERT INTO ping_status (id, server_id, ts, is_online, latency_ms)
                VALUES (?, ?, ?, ?, ?)
            """, (ping_id, server["id"], now, is_online, latency_ms))
            
        except Exception as e:
            print(f"Ping {server['name']} ({server['ip']}) 失败: {e}")
            # 记录失败
            ping_id = id_gen.next_id()
            cursor.execute("""
                INSERT INTO ping_status (id, server_id, ts, is_online, latency_ms)
                VALUES (?, ?, ?, ?, ?)
            """, (ping_id, server["id"], now, 0, None))
    
    conn.commit()
    conn.close()


def get_server_health_status(server_id):
    """获取服务器当前健康状态"""
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    
    # Ping 健康状态
    # 正常：最近 2 分钟内有成功记录
    cursor.execute("""
        SELECT is_online FROM ping_status 
        WHERE server_id = ? AND ts >= ?
        ORDER BY ts DESC LIMIT 1
    """, (server_id, now - 120))
    row = cursor.fetchone()
    
    ping_health = "down"
    if row and row[0] == 1:
        ping_health = "ok"
    else:
        # 警告：最近 2 分钟失败，但过去 10 分钟内有成功
        cursor.execute("""
            SELECT COUNT(*) FROM ping_status 
            WHERE server_id = ? AND ts >= ? AND is_online = 1
        """, (server_id, now - 600))
        count = cursor.fetchone()[0]
        if count > 0:
            ping_health = "warn"
    
    # 上报健康状态
    # 正常：最近 2 分钟有心跳
    cursor.execute("""
        SELECT COUNT(*) FROM heartbeat_status 
        WHERE server_id = ? AND ts >= ?
    """, (server_id, now - 120))
    count = cursor.fetchone()[0]
    heartbeat_health = "ok" if count > 0 else "down"
    
    conn.close()
    return {"ping_health": ping_health, "heartbeat_health": heartbeat_health}


def get_24h_timeline(server_id, slots=288):
    """获取过去 24 小时的时间线数据（288 个 5 分钟槽位）"""
    conn = get_db()
    cursor = conn.cursor()
    now = int(time.time())
    start_time = now - 24 * 3600
    slot_duration = 24 * 3600 // slots
    
    timeline = []
    
    for i in range(slots):
        slot_start = start_time + i * slot_duration
        slot_end = slot_start + slot_duration
        
        # 查询该时间段内的 ping 状态
        cursor.execute("""
            SELECT AVG(is_online) as avg_online FROM ping_status
            WHERE server_id = ? AND ts >= ? AND ts < ?
        """, (server_id, slot_start, slot_end))
        row = cursor.fetchone()
        ping_status = 0  # 0=无数据, 1=正常, -1=部分失败
        if row and row[0] is not None:
            avg = row[0]
            if avg >= 0.8:
                ping_status = 1
            elif avg > 0:
                ping_status = -1
        
        # 查询该时间段内的心跳状态
        cursor.execute("""
            SELECT COUNT(*) FROM heartbeat_status
            WHERE server_id = ? AND ts >= ? AND ts < ?
        """, (server_id, slot_start, slot_end))
        row = cursor.fetchone()
        heartbeat_status = 1 if row and row[0] > 0 else 0
        
        timeline.append({
            "ping": ping_status,
            "heartbeat": heartbeat_status
        })
    
    conn.close()
    return timeline


def get_latest_resource_usage(server_id):
    """获取服务器最近一次心跳的 CPU / 内存占用"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT cpu_load, mem_load FROM heartbeat_status
        WHERE server_id = ?
        ORDER BY ts DESC
        LIMIT 1
        """,
        (server_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"cpu": None, "mem": None}

    return {"cpu": row["cpu_load"], "mem": row["mem_load"]}


def get_server_resource_series(server_id, points=60):
    """获取过去 24 小时 CPU / 内存占用曲线（按时间均分聚合）"""
    conn = get_db()
    cursor = conn.cursor()

    now = int(time.time())
    start_time = now - 24 * 3600
    total_seconds = 24 * 3600
    slot_duration = total_seconds / points

    # 先把 24 小时内所有心跳取出来，按时间槽聚合
    cursor.execute(
        """
        SELECT ts, cpu_load, mem_load
        FROM heartbeat_status
        WHERE server_id = ? AND ts >= ?
        ORDER BY ts ASC
        """,
        (server_id, start_time),
    )
    rows = cursor.fetchall()

    buckets = [
        {"cpu_sum": 0.0, "cpu_count": 0, "mem_sum": 0.0, "mem_count": 0}
        for _ in range(points)
    ]

    for row in rows:
        ts = row["ts"]
        cpu = row["cpu_load"]
        mem = row["mem_load"]

        idx = int((ts - start_time) // slot_duration)
        if idx < 0:
            continue
        if idx >= points:
            idx = points - 1

        bucket = buckets[idx]
        if cpu is not None:
            bucket["cpu_sum"] += cpu
            bucket["cpu_count"] += 1
        if mem is not None:
            bucket["mem_sum"] += mem
            bucket["mem_count"] += 1

    series = []
    for i in range(points):
        slot_start = start_time + int(i * slot_duration)
        b = buckets[i]
        cpu_avg = b["cpu_sum"] / b["cpu_count"] if b["cpu_count"] > 0 else None
        mem_avg = b["mem_sum"] / b["mem_count"] if b["mem_count"] > 0 else None
        series.append(
            {
                "ts": slot_start,
                "cpu": cpu_avg,
                "mem": mem_avg,
            }
        )

    conn.close()
    return series


def get_status_page_data():
    """获取状态页面所需的所有数据"""
    servers = get_all_servers()
    
    server_data = []
    overall_status = "ok"
    
    for server in servers:
        health = get_server_health_status(server["id"])
        timeline = get_24h_timeline(server["id"])
        latest_usage = get_latest_resource_usage(server["id"])
        resource_series = get_server_resource_series(server["id"])
        
        # 更新整体状态
        if health["ping_health"] == "down" or health["heartbeat_health"] == "down":
            overall_status = "error"
        elif health["ping_health"] == "warn" and overall_status == "ok":
            overall_status = "warn"
        
        server_data.append({
            "id": server["id"],
            "name": server["name"],
            "ip": server["ip"],
            "ping_health": health["ping_health"],
            "heartbeat_health": health["heartbeat_health"],
            "timeline": timeline,
            "current_cpu": latest_usage["cpu"],
            "current_mem": latest_usage["mem"],
            "resource_series": resource_series,
        })
    
    return {
        "overall_status": overall_status,
        "servers": server_data
    }


def get_server_status_data(server_id):
    """获取单个服务器的详细状态数据"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 获取服务器信息
    cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    server = cursor.fetchone()
    if not server:
        conn.close()
        return None
    
    now = int(time.time())
    day_ago = now - 24 * 3600
    
    # 获取 24 小时内的 ping 数据
    cursor.execute("""
        SELECT ts, is_online, latency_ms FROM ping_status
        WHERE server_id = ? AND ts >= ?
        ORDER BY ts ASC
    """, (server_id, day_ago))
    ping_data = [dict(row) for row in cursor.fetchall()]
    
    # 获取 24 小时内的心跳数据
    cursor.execute("""
        SELECT ts, up_bytes, down_bytes, cpu_load, mem_load, ip FROM heartbeat_status
        WHERE server_id = ? AND ts >= ?
        ORDER BY ts ASC
    """, (server_id, day_ago))
    heartbeat_data = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "server": dict(server),
        "ping_data": ping_data,
        "heartbeat_data": heartbeat_data
    }

