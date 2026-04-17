#!/bin/bash
# 获取蓝湖设计图的标注数据（Schema JSON）
# 用法: bash get_annotation.sh [image_id] [team_id] [project_id]
# 示例: bash get_annotation.sh fe7cd010-a89c-4ea8-b8b9-4401b4519413 a62f8ede-71ee-490b-85df-667e49159227 922b49c9-d582-462f-80dd-e4ceac466e4b

set -e

IMAGE_ID="${1:-fe7cd010-a89c-4ea8-b8b9-4401b4519413}"
TEAM_ID="${2:-a62f8ede-71ee-490b-85df-667e49159227}"
PROJECT_ID="${3:-922b49c9-d582-462f-80dd-e4ceac466e4b}"
COOKIE_FILE="$HOME/Desktop/lanhu-mcp/.env"
OUTPUT_FILE="/tmp/schema_json.json"

echo "=========================================="
echo "  蓝湖标注数据获取"
echo "=========================================="
echo "image_id: $IMAGE_ID"
echo "team_id:  $TEAM_ID"
echo "project_id: $PROJECT_ID"
echo ""

# 读取 Cookie
COOKIE=$(grep 'LANHU_COOKIE=' "$COOKIE_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
if [ -z "$COOKIE" ]; then
    echo "❌ 未找到 LANHU_COOKIE，请检查 $COOKIE_FILE"
    exit 1
fi
echo "✅ Cookie 已加载 ($(echo $COOKIE | cut -c1-20)...)"

# Step 1: 获取 version_id
echo ""
echo "📍 Step 1: 获取 version_id..."
VERSION_ID=$(curl -s "$LANHUAPP_URL/api/project/multi_info" \
    -H "Cookie: $COOKIE" \
    -H "Referer: https://lanhuapp.com/web/" \
    -G --data-urlencode "project_id=$PROJECT_ID" \
    --data-urlencode "team_id=$TEAM_ID" \
    --data-urlencode "img_limit=500" \
    --data-urlencode "detach=1" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); imgs=d.get('result',{}).get('images',[]); [print(img.get('latest_version')) for img in imgs if img.get('id')=='$IMAGE_ID']")

if [ -z "$VERSION_ID" ]; then
    echo "❌ 未找到 version_id"
    exit 1
fi
echo "✅ version_id: $VERSION_ID"

# Step 2: 获取 Schema URL
echo ""
echo "📍 Step 2: 获取 Schema URL..."
SCHEMA_URL=$(curl -s "https://dds.lanhuapp.com/api/dds/image/store_schema_revise?version_id=$VERSION_ID" \
    -H "Cookie: $COOKIE" \
    -H "Referer: https://dds.lanhuapp.com/" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',{}).get('data_resource_url',''))")

if [ -z "$SCHEMA_URL" ]; then
    echo "❌ 未找到 schema URL"
    exit 1
fi
echo "✅ Schema URL: ${SCHEMA_URL:0:80}..."

# Step 3: 下载 Schema JSON（可能受 DNS 封锁，尝试多方案）
echo ""
echo "📍 Step 3: 下载 Schema JSON..."

# 方案A: 直接 curl（有时成功，有时被 DNS 封锁）
download_with_curl() {
    curl -s "$SCHEMA_URL" \
        -H "Cookie: $COOKIE" \
        -H "Referer: https://dds.lanhuapp.com/" \
        -o "$OUTPUT_FILE" \
        --max-time 30
    local size=$(wc -c < "$OUTPUT_FILE")
    [ "$size" -gt 100 ]
}

# 方案B: DNS 绕过（系统 DNS 被污染时使用）
download_with_dns_bypass() {
    # 用公共 DNS 查询真实 IP
    DOMAIN=$(echo "$SCHEMA_URL" | sed -E 's|https?://([^/]+)/.*|\1|')
    REAL_IP=$(dig +short @"8.8.8.8" "$DOMAIN" 2>/dev/null | tail -1)

    if [ -z "$REAL_IP" ] || [ "$REAL_IP" = "0.0.0.0" ]; then
        REAL_IP=$(nslookup "$DOMAIN" 8.8.8.8 2>/dev/null | grep "Address:" | tail -1 | awk '{print $2}')
    fi

    echo "   🔄 公共DNS解析: $DOMAIN → $REAL_IP"

    curl -s "https://$SCHEMA_URL" \
        -H "Cookie: $COOKIE" \
        -H "Referer: https://dds.lanhuapp.com/" \
        -H "Host: $DOMAIN" \
        --connect-to "$DOMAIN:443:$REAL_IP:443" \
        -k \
        -o "$OUTPUT_FILE" \
        --max-time 30
    local size=$(wc -c < "$OUTPUT_FILE" 2>/dev/null || echo 0)
    [ "$size" -gt 100 ]
}

# 方案C: Python DNS 绕过（直连已知 IP）
download_with_python() {
    python3 -c "
import ssl, http.client, json, socket, subprocess, re, sys

domain = '$DOMAIN' if '$DOMAIN' else '$({ python3 -c "import re; url='$SCHEMA_URL'; m=re.match(r'https?://([^/]+)', url); print(m.group(1) if m else '')" })'
path = '$({ python3 -c "import re; url='$SCHEMA_URL'; m=re.match(r'https?://[^/]+(/.*)', url); print(m.group(1) if m else '/')" })'

try:
    result = subprocess.run(['dig', '+short', '@8.8.8.8', domain], capture_output=True, text=True, timeout=10)
    ip = result.stdout.strip().split('\n')[-1]
    if not ip or '.' not in ip:
        raise Exception('DNS failed')
    print(f'DNS resolved: {domain} → {ip}')

    ctx = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection(ip, 443, timeout=20, context=ctx)
    conn.connect()
    conn.request('GET', path, headers={
        'Host': domain,
        'Cookie': '$COOKIE',
        'Referer': 'https://dds.lanhuapp.com/',
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    resp = conn.getresponse()
    data = resp.read()
    if resp.status == 200 and len(data) > 100:
        schema = json.loads(data)
        with open('$OUTPUT_FILE', 'w') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        print(f'Downloaded via DNS bypass: {len(data)} bytes')
    else:
        print(f'HTTP {resp.status}, {len(data)} bytes')
        sys.exit(1)
except Exception as e:
    print(f'DNS bypass failed: {e}')
    sys.exit(1)
" 2>&1
}

# 尝试方案A
if download_with_curl; then
    SIZE=$(wc -c < "$OUTPUT_FILE")
    echo "✅ 直接下载成功: $SIZE bytes"
else
    echo "⚠️ 直接下载失败（DNS 封锁），尝试 DNS 绕过..."
    download_with_python
    SIZE=$(wc -c < "$OUTPUT_FILE" 2>/dev/null || echo 0)
fi
echo "✅ 下载完成: $SIZE bytes → $OUTPUT_FILE"

# 检查是否下载成功
if [ "$SIZE" -lt 100 ]; then
    echo "❌ 文件太小，可能下载失败"
    cat "$OUTPUT_FILE"
    exit 1
fi

echo ""
echo "=========================================="
echo "  获取完成！"
echo "=========================================="
echo "文件: $OUTPUT_FILE"
echo ""
echo "下一步：在 Claude 中运行："
echo "  python3 -c \"import json; d=json.load(open('$OUTPUT_FILE')); print(list(d.keys())[:10])\""
