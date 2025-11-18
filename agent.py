#!/usr/bin/env python3
"""
VPS 状态监控客户端
采集本机 CPU、内存、网络流量并上报到服务端
"""

import argparse
import sys
import time
import json

try:
    import psutil
except ImportError:
    print("错误：需要安装 psutil 库")
    print("运行：pip install psutil")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("错误：需要安装 requests 库")
    print("运行：pip install requests")
    sys.exit(1)


def collect_metrics():
    """采集系统指标"""
    try:
        # CPU 负载（百分比）
        cpu_load = psutil.cpu_percent(interval=1)
        
        # 内存使用率（百分比）
        mem = psutil.virtual_memory()
        mem_load = mem.percent
        
        # 网络流量（累计字节数）
        net = psutil.net_io_counters()
        up_bytes = net.bytes_sent
        down_bytes = net.bytes_recv
        
        return {
            "cpu_load": cpu_load,
            "mem_load": mem_load,
            "up_bytes": up_bytes,
            "down_bytes": down_bytes
        }
    except Exception as e:
        print(f"采集指标失败: {e}")
        return None


def report_heartbeat(server_url, server_id=None, server_name=None, metrics=None):
    """上报心跳到服务端"""
    if not metrics:
        return False


def register_server(server_url, server_name):
    """向服务端注册，返回服务器 ID"""
    try:
        if not server_name:
            print("错误：注册时必须提供服务器名称")
            return None

        url = f"{server_url.rstrip('/')}/api/register"
        resp = requests.post(url, json={"name": server_name}, timeout=10)
        if resp.status_code != 200:
            print(f"注册失败: HTTP {resp.status_code} - {resp.text}")
            return None

        data = resp.json()
        srv = data.get("server") or {}
        server_id = srv.get("id")
        if not server_id:
            print(f"注册失败: 服务端未返回服务器ID: {data}")
            return None

        print(f"注册成功 - 服务器名称: {srv.get('name')}, IP: {srv.get('ip')}, 服务器ID: {server_id}")
        return server_id
    except requests.exceptions.ConnectionError:
        print(f"连接失败: 无法连接到 {server_url}")
        return None
    except requests.exceptions.Timeout:
        print("注册请求超时")
        return None
    except Exception as e:
        print(f"注册异常: {e}")
        return None
    
    try:
        # 构建请求数据
        data = {
            "cpu_load": metrics["cpu_load"],
            "mem_load": metrics["mem_load"],
            "up_bytes": metrics["up_bytes"],
            "down_bytes": metrics["down_bytes"]
        }
        
        if server_id:
            data["server_id"] = server_id
        elif server_name:
            data["server_name"] = server_name
        else:
            print("错误：必须提供 --server-id 或 --server-name")
            return False
        
        # 发送请求
        url = f"{server_url.rstrip('/')}/api/heartbeat"
        response = requests.post(url, json=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            print(f"上报成功 - CPU: {metrics['cpu_load']:.1f}%, "
                  f"内存: {metrics['mem_load']:.1f}%, "
                  f"上行: {metrics['up_bytes']}, "
                  f"下行: {metrics['down_bytes']}")
            return True
        else:
            print(f"上报失败: HTTP {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"连接失败: 无法连接到 {server_url}")
        return False
    except requests.exceptions.Timeout:
        print("上报超时")
        return False
    except Exception as e:
        print(f"上报异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="VPS 状态监控客户端")
    parser.add_argument("--server-url", required=True, help="服务端地址，例如: http://192.168.1.100:8000")
    parser.add_argument("--server-id", help="服务器ID（优先使用）")
    parser.add_argument("--server-name", help="服务器名称（如果未提供 server-id）")
    parser.add_argument("--interval", type=int, default=60, help="上报间隔（秒），默认 60")
    parser.add_argument("--once", action="store_true", help="只上报一次后退出")
    parser.add_argument("--register", action="store_true", help="仅注册并打印服务器ID，不进行心跳上报")
    
    args = parser.parse_args()
    
    # 注册模式：只向服务端注册并打印 ID
    if args.register:
        if not args.server_name:
            print("错误：注册模式必须提供 --server-name")
            sys.exit(1)
        server_id = register_server(args.server_url, args.server_name)
        if server_id:
            # 只打印一次就退出，方便拷贝 ID 去用
            print(f"请保存该服务器ID，用于后续心跳上报: {server_id}")
            sys.exit(0)
        else:
            sys.exit(1)

    # 普通心跳模式需要有 server-id 或 server-name
    if not args.server_id and not args.server_name:
        print("错误：必须提供 --server-id 或 --server-name（或者使用 --register 先注册）")
        sys.exit(1)
    
    print(f"VPS 状态监控客户端启动")
    print(f"服务端: {args.server_url}")
    if args.server_id:
        print(f"服务器ID: {args.server_id}")
    else:
        print(f"服务器名称: {args.server_name}")
    
    if args.once:
        print("模式: 单次上报")
        # 单次上报模式
        metrics = collect_metrics()
        if metrics:
            success = report_heartbeat(args.server_url, args.server_id, args.server_name, metrics)
            sys.exit(0 if success else 1)
        else:
            print("采集指标失败")
            sys.exit(1)
    else:
        print(f"模式: 循环上报（间隔 {args.interval} 秒）")
        print("按 Ctrl+C 退出")
        
        # 循环上报模式
        while True:
            try:
                metrics = collect_metrics()
                if metrics:
                    report_heartbeat(args.server_url, args.server_id, args.server_name, metrics)
                else:
                    print("采集指标失败，跳过本次上报")
                
                time.sleep(args.interval)
                
            except KeyboardInterrupt:
                print("\n客户端已停止")
                sys.exit(0)
            except Exception as e:
                print(f"运行异常: {e}")
                # 不退出，继续尝试
                time.sleep(args.interval)


if __name__ == "__main__":
    main()

