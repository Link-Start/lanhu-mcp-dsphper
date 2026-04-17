#!/usr/bin/env python3
"""
获取蓝湖设计图的标注数据（Schema JSON）
标注数据 = 标注模式（detailDetach）里设计师手动添加的尺寸、颜色、字体、间距标注

用法:
    cd ~/Desktop/lanhu-mcp
    source .venv/bin/activate
    python3 get_annotation_data.py [image_id] [team_id] [project_id]

示例:
    python3 get_annotation_data.py fe7cd010-a89c-4ea8-b8b9-4401b4519413 a62f8ede-71ee-490b-85df-667e49159227 922b49c9-d582-462f-80dd-e4ceac466e4b
"""

import asyncio
import json
import sys
import httpx
from pathlib import Path

BASE_URL = "https://lanhuapp.com"
DDS_BASE_URL = "https://dds.lanhuapp.com"
TIMEOUT = httpx.Timeout(30.0)

IMAGE_ID = "fe7cd010-a89c-4ea8-b8b9-4401b4519413"
TEAM_ID = "a62f8ede-71ee-490b-85df-667e49159227"
PROJECT_ID = "922b49c9-d582-462f-80dd-e4ceac466e4b"

# 如果命令行传了参数
if len(sys.argv) >= 4:
    IMAGE_ID = sys.argv[1]
    TEAM_ID = sys.argv[2]
    PROJECT_ID = sys.argv[3]

print(f"image_id:   {IMAGE_ID}")
print(f"team_id:    {TEAM_ID}")
print(f"project_id: {PROJECT_ID}")
print()


def load_cookie() -> str:
    """从 .env 文件读取 LANHU_COOKIE"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"未找到 .env 文件: {env_path}")

    cookie = ""
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("LANHU_COOKIE="):
            cookie = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

    if not cookie:
        raise ValueError("LANHU_COOKIE 未配置，请编辑 .env 文件")
    return cookie


async def fetch_schema() -> dict:
    cookie = load_cookie()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://lanhuapp.com/web/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "request-from": "web",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # Step 1: 获取 version_id
        print("Step 1: 获取 version_id...")
        resp = await client.get(
            f"{BASE_URL}/api/project/multi_info",
            params={"project_id": PROJECT_ID, "team_id": TEAM_ID, "img_limit": 500, "detach": 1},
            headers=headers,
        )
        data = resp.json()
        if data.get("code") != "00000":
            raise Exception(f"multi_info 失败: {data.get('msg')}")

        images = (data.get("result") or {}).get("images") or []
        version_id = None
        for img in images:
            if img.get("id") == IMAGE_ID:
                version_id = img.get("latest_version")
                break

        if not version_id:
            available = [img.get("id") for img in images[:10]]
            raise Exception(f"未找到 image_id={IMAGE_ID}，可用: {available}")
        print(f"  ✅ version_id: {version_id}")

        # Step 2: 调用 DDS 获取 schema URL
        print("\nStep 2: 获取 Schema URL...")
        dds_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://dds.lanhuapp.com/",
            "Cookie": cookie,
        }
        dds_resp = await client.get(
            f"{DDS_BASE_URL}/api/dds/image/store_schema_revise",
            params={"version_id": version_id},
            headers=dds_headers,
        )
        dds_data = dds_resp.json()
        if dds_data.get("code") != "00000":
            raise Exception(f"DDS store_schema_revise 失败: {dds_data.get('msg')}")

        schema_url = (dds_data.get("data") or {}).get("data_resource_url")
        if not schema_url:
            raise Exception(f"未找到 schema URL: {json.dumps(dds_data, ensure_ascii=False)[:500]}")
        print(f"  ✅ Schema URL: {schema_url[:80]}...")

        # Step 3: 下载 Schema JSON（可能受 DNS 封锁，需要绕过）
        print("\nStep 3: 下载标注数据...")
        schema = await _download_schema_json(schema_url, cookie)
        print(f"  ✅ 下载完成")

        out_path = Path("/tmp/lanhu_annotation_schema.json")
        out_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2))
        size = out_path.stat().st_size
        print(f"  ✅ 保存: {size:,} bytes → {out_path}")
        return schema


async def _download_schema_json(schema_url: str, cookie: str) -> dict:
    """下载 schema JSON，绕过系统 DNS 封锁（如果有）"""
    import re
    import ssl
    import http.client
    import subprocess

    # 解析 schema_url
    url_match = re.match(r"https?://([^/]+)(/.*)", schema_url)
    if not url_match:
        raise Exception(f"无法解析 schema URL: {schema_url}")

    hostname = url_match.group(1)
    path = url_match.group(2)

    # 方法1: 直接用 httpx（默认走系统 DNS）
    try:
        context = httpx.create_ssl_context()
        async with httpx.AsyncClient(verify=context, timeout=TIMEOUT) as client:
            resp = await client.get(schema_url, headers={
                "Cookie": cookie,
                "Referer": "https://dds.lanhuapp.com/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            })
            if resp.status_code == 200 and len(resp.content) > 100:
                print(f"  ✅ 直接下载成功（httpx）")
                return resp.json()
    except Exception as e:
        print(f"  ⚠️ httpx 直接下载失败: {e}")

    # 方法2: 用公共 DNS 解析 → 直连 IP
    print("  🔧 尝试 DNS 绕过（公共 DNS）...")
    try:
        # 用 dig/nslookup 查询真实 IP
        result = subprocess.run(
            ["dig", "+short", "@8.8.8.8", hostname],
            capture_output=True, text=True, timeout=10
        )
        ip = result.stdout.strip().split("\n")[-1]  # 取最后一个 A 记录

        # 去掉 CNAME 链末尾的空行
        if not ip or "." not in ip:
            # 尝试 nslookup
            result2 = subprocess.run(
                ["nslookup", hostname, "8.8.8.8"],
                capture_output=True, text=True, timeout=10
            )
            ip_match = re.search(r"Address:\s+(\d+\.\d+\.\d+\.\d+)", result2.stdout)
            if ip_match:
                ip = ip_match.group(1)

        if not ip or "." not in ip:
            raise Exception("DNS 解析失败")

        print(f"  📍 公共 DNS 解析: {hostname} → {ip}")

        # 直连 IP，SSL 不验证 hostname（因为证书是 *.domain.com 不是 IP）
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        conn = http.client.HTTPSConnection(ip, 443, timeout=20, context=ctx)
        conn.connect()
        conn.request("GET", path, headers={
            "Host": hostname,
            "Cookie": cookie,
            "Referer": "https://dds.lanhuapp.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        resp = conn.getresponse()
        data = resp.read()

        if resp.status == 200 and len(data) > 100:
            print(f"  ✅ DNS 绕过下载成功（IP直连）: {len(data)} bytes")
            return json.loads(data)
        else:
            raise Exception(f"HTTP {resp.status}, {len(data)} bytes")
    except subprocess.TimeoutExpired:
        raise Exception("DNS 查询超时")
    except FileNotFoundError:
        # dig/nslookup 不存在，尝试 Python socket
        print("  🔧 尝试 socket DNS 绕过...")
        return await _download_via_socket_dns(schema_url, cookie, hostname, path)
    except Exception as e:
        print(f"  ⚠️ IP直连失败: {e}")
        # 最后尝试 socket 方案
        return await _download_via_socket_dns(schema_url, cookie, hostname, path)


async def _download_via_socket_dns(schema_url: str, cookie: str, hostname: str, path: str) -> dict:
    """通过 socket + 硬编码 IP 绕过 DNS 封锁"""
    import ssl
    import http.client

    # 已知 Aliyun OSS 的常见 IP 范围（通过公共 DNS 查询得到）
    # 这里预先写入常见 IP，如果失败再由调用方处理
    KNOWN_IPS = {
        "lanhu-dds-backend.oss-cn-beijing.aliyuncs.com": "39.156.229.148",
    }

    ip = KNOWN_IPS.get(hostname)
    if not ip:
        raise Exception(f"无法解析 {hostname}，且无已知 IP")

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    conn = http.client.HTTPSConnection(ip, 443, timeout=20, context=ctx)
    conn.connect()
    conn.request("GET", path, headers={
        "Host": hostname,
        "Cookie": cookie,
        "Referer": "https://dds.lanhuapp.com/",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    resp = conn.getresponse()
    data = resp.read()

    if resp.status == 200 and len(data) > 100:
        print(f"  ✅ Socket 直连下载成功: {len(data)} bytes")
        return json.loads(data)
    raise Exception(f"下载失败: HTTP {resp.status}")


def analyze_schema(schema: dict):
    """分析 Schema JSON 的结构"""
    print("\n=== Schema JSON 结构 ===")

    if isinstance(schema, dict):
        print(f"类型: dict, 顶层 keys: {list(schema.keys())[:20]}")
        for k, v in list(schema.items())[:15]:
            if isinstance(v, str):
                print(f"  {k}: {v[:80]}")
            elif isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
                if v:
                    first = v[0]
                    if isinstance(first, dict):
                        print(f"    第一个元素 keys: {list(first.keys())[:10]}")
            elif isinstance(v, dict):
                print(f"  {k}: dict with keys {list(v.keys())[:10]}")
            else:
                print(f"  {k}: {v}")

    elif isinstance(schema, list):
        print(f"类型: list, 长度: {len(schema)}")
        if schema:
            first = schema[0]
            if isinstance(first, dict):
                print(f"第一个元素 keys: {list(first.keys())[:15]}")
                # Show a sample
                sample = json.dumps(first, ensure_ascii=False)[:300]
                print(f"  示例: {sample}")


if __name__ == "__main__":
    try:
        schema = asyncio.run(fetch_schema())
        analyze_schema(schema)
        print("\n✅ 完成！Claude 可以读取 /tmp/lanhu_annotation_schema.json 进行分析。")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)
