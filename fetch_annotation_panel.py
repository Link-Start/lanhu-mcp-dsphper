#!/usr/bin/env python3
"""直接抓取蓝湖 detailDetach 页面右侧标注面板 DOM 值。

用法：
    python fetch_annotation_panel.py <detailDetach_url>

优先复用本机 Chrome 已登录会话，Cookie 失效时回退到 .env Cookie。
"""

import asyncio
import json
import re
import shutil
import tempfile
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

ENV_PATH = Path("/Users/link/Desktop/lanhu-mcp/.env")
OUT_PATH = Path("/tmp/lanhu_panel_data.json")

# Chrome 用户配置根目录 + 具体 Profile
CHROME_USER_DATA_DIR = "/Users/link/Library/Application Support/Google/Chrome"
CHROME_PROFILE_DIR = "Profile 4"  # 已确认这里有 lanhuapp.com Cookie
# 如需切换，改成 Default / Profile 5 等。

DEFAULT_TID = "a62f8ede-71ee-490b-85df-667e49159227"
DEFAULT_PID = "922b49c9-d582-462f-80dd-e4ceac466e4b"
DEFAULT_IMAGE_ID = "fe7cd010-a89c-4ea8-b8b9-4401b4519413"


def parse_target_from_url(url: str):
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    if not query and parsed.fragment and "?" in parsed.fragment:
        fragment_query = parsed.fragment.split("?", 1)[1]
        query = urllib.parse.parse_qs(fragment_query)

    tid = (query.get("tid") or [DEFAULT_TID])[0]
    pid = (query.get("pid") or query.get("project_id") or [DEFAULT_PID])[0]
    image_id = (query.get("image_id") or [DEFAULT_IMAGE_ID])[0]
    return tid, pid, image_id


def build_detail_detach_url(tid: str, pid: str, image_id: str):
    return (
        f"https://lanhuapp.com/web/#/item/project/detailDetach"
        f"?tid={tid}&pid={pid}&image_id={image_id}"
    )


def build_sso_url(tid: str, pid: str, image_id: str):
    next_url_encoded = urllib.parse.quote(
        f"item/board/detail?tid={tid}&pid={pid}"
        f"&image_id={image_id}&type=projectdetail",
        safe=""
    )
    return (
        f"https://lanhuapp.com/sso/?tid={tid}"
        f"&redirect_to=https://lanhuapp.com/web/%23/{next_url_encoded}"
    )


def build_detail_url_with_sso(tid: str, pid: str, image_id: str, sso_token=None):
    next_url = urllib.parse.quote(
        f"item/board/detail?tid={tid}&pid={pid}"
        f"&image_id={image_id}&type=projectdetail",
        safe=""
    )
    base = "https://lanhuapp.com/web/"
    params = [f"referrer=inner_link", f"next_url={next_url}"]
    if sso_token:
        params.append(f"sso_token={urllib.parse.quote(sso_token)}")
    return base + "?" + "&".join(params) + f"#/item/project/detailDetach%3Ftid%3D{tid}%26pid%3D{pid}%26image_id%3D{image_id}"



def load_cookie() -> str:
    text = ENV_PATH.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^LANHU_COOKIE=(.*)$", text, re.M)
    if not m:
        raise RuntimeError("LANHU_COOKIE not found in .env")
    return m.group(1).strip().strip('"').strip("'")


def cookie_string_to_playwright(cookie_str: str):
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".lanhuapp.com",
            "path": "/",
        })
    return cookies


PANEL_EXTRACT_JS = r"""() => {
    var text = function(el) { return (el ? el.textContent : "").trim(); };
    var all = Array.from(document.querySelectorAll("*"));

    var result = {
        platform_header: null,
        layer_name: null,
        position: null,
        size: null,
        opacity: null,
        font_family: null,
        font_weight: null,
        text_align: null,
        text_color: null,
        font_size: null,
        letter_spacing: null,
        line_height: null,
        page_text_snapshot: (document.body ? document.body.innerText : "").slice(0, 6000)
    };

    // 找到平台头
    var headerEl = all.find(function(el) {
        var t = text(el);
        return /iOS.*375.*812.*pt/i.test(t);
    });
    if (headerEl) result.platform_header = text(headerEl);

    // 找 label 对应的值（向上找父级兄弟节点）
    function readPair(label) {
        var labelEl = all.find(function(el) { return text(el) === label; });
        if (!labelEl) return null;
        var box = labelEl.parentElement;
        for (var i = 0; i < 6 && box; i++) {
            box = box.parentElement;
            if (!box) break;
            var vals = Array.from(box.querySelectorAll("*"))
                .map(function(el) { return text(el); })
                .filter(function(t) { return t && t !== label; });
            if (vals.length > 0) return vals;
        }
        return null;
    }

    var layerVals = readPair("\u56fe\u5c42");
    if (layerVals && layerVals.length) result.layer_name = layerVals[0];

    var posVals = readPair("\u4f4d\u7f6e");
    if (posVals && posVals.length >= 2) result.position = { x: posVals[0], y: posVals[1] };

    var sizeVals = readPair("\u5927\u5c0f");
    if (sizeVals && sizeVals.length >= 2) result.size = { width: sizeVals[0], height: sizeVals[1] };

    var opacityVals = readPair("\u4e0d\u900f\u660e\u5ea6");
    if (opacityVals && opacityVals.length) result.opacity = opacityVals[0];

    var familyVals = readPair("\u5b57\u4f53");
    if (familyVals && familyVals.length) result.font_family = familyVals[0];

    var weightVals = readPair("\u5b57\u91cd");
    if (weightVals && weightVals.length) result.font_weight = weightVals[0];

    var alignVals = readPair("\u5bf9\u9f50");
    if (alignVals && alignVals.length) result.text_align = alignVals[0];

    var fontSizeVals = readPair("\u5b57\u53f7");
    if (fontSizeVals && fontSizeVals.length) result.font_size = fontSizeVals[0];

    var lineHeightVals = readPair("\u884c\u9ad8");
    if (lineHeightVals && lineHeightVals.length) result.line_height = lineHeightVals[0];

    var trackingVals = readPair("\u5b57\u95f4\u8ddd");
    if (trackingVals && trackingVals.length) result.letter_spacing = trackingVals[0];

    // 找 HEX 颜色值
    var hexEl = all.find(function(el) { return /^[0-9A-Fa-f]{6}$/.test(text(el).replace("#","")); });
    if (hexEl) result.text_color = "#" + text(hexEl).replace("#","");

    // 直接搜索面板里含 pt 的所有文本片段
    var ptMatches = [];
    all.forEach(function(el) {
        var t = text(el);
        if (/\d+\.?\d*\s*pt/i.test(t) && t.length < 50) {
            ptMatches.push(t);
        }
    });
    result.pt_snippets = ptMatches.slice(0, 30);

    return result;
}"""


async def try_chrome_context(p: async_playwright):
    """尝试用本机 Chrome 已登录会话。

    Chrome 不允许直接把真实默认用户目录用于 DevTools 调试，
    所以这里复制最小必要文件到临时 user-data-dir 后再启动。
    """
    chrome_root = Path(CHROME_USER_DATA_DIR)
    profile_dir = chrome_root / CHROME_PROFILE_DIR
    if not chrome_root.exists() or not profile_dir.exists():
        print(f"[Chrome] 用户目录不存在: {chrome_root} / {profile_dir}")
        return None

    temp_root = Path(tempfile.mkdtemp(prefix="lanhu-chrome-"))
    temp_profile = temp_root / CHROME_PROFILE_DIR
    temp_profile.mkdir(parents=True, exist_ok=True)

    try:
        # 复制最小会话文件
        files_to_copy = [
            chrome_root / "Local State",
            profile_dir / "Cookies",
            profile_dir / "Cookies-journal",
            profile_dir / "Preferences",
            profile_dir / "Secure Preferences",
            profile_dir / "Network Persistent State",
            profile_dir / "TransportSecurity",
        ]
        dirs_to_copy = [
            profile_dir / "Local Storage",
            profile_dir / "Session Storage",
            profile_dir / "Sessions",
            profile_dir / "WebStorage",
            profile_dir / "IndexedDB",
            profile_dir / "Service Worker",
        ]

        for src in files_to_copy:
            if src.exists():
                target = temp_root / src.name if src.parent == chrome_root else temp_profile / src.name
                shutil.copy2(src, target)

        for src in dirs_to_copy:
            if src.exists():
                shutil.copytree(src, temp_profile / src.name, dirs_exist_ok=True)

        context = await p.chromium.launch_persistent_context(
            str(temp_root),
            channel="chrome",
            headless=False,
            viewport={"width": 1800, "height": 1200},
            args=[
                "--no-first-run",
                "--disable-background-timer-throttling",
                f"--profile-directory={CHROME_PROFILE_DIR}",
            ],
        )
        print(f"[Chrome] 成功复用 Chrome 会话副本 (Profile={CHROME_PROFILE_DIR})")
        return context
    except Exception as e:
        print(f"[Chrome] 启动失败: {e}")
        return None


async def dump_cookie_names(context):
    try:
        cookies = await context.cookies(["https://lanhuapp.com"])
        names = sorted({c.get("name", "") for c in cookies})
        print(f"[CookieNames] {names}")
    except Exception as e:
        print(f"[CookieNames] 读取失败: {e}")
        return None
    return None


async def debug_lanhu_api(page):
    js = r'''async () => {
        const urls = [
            'https://lanhuapp.com/api/dayu/design/project/permission',
            'https://lanhuapp.com/api/account/entry?sso_team_id=a62f8ede-71ee-490b-85df-667e49159227'
        ];
        const out = [];
        for (const url of urls) {
            try {
                const resp = await fetch(url, { credentials: 'include' });
                const text = await resp.text();
                out.push({ url, status: resp.status, body: text.slice(0, 300) });
            } catch (e) {
                out.push({ url, error: String(e) });
            }
        }
        return out;
    }'''
    try:
        result = await page.evaluate(js)
        print('[APIDebug]', json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(f'[APIDebug] 执行失败: {e}')
        return None
    return None


async def is_login_page(page):
    body_text = await page.evaluate("document.body ? document.body.innerText.slice(0, 2000) : ''")
    bad_signs = [
        '欢迎来到蓝湖',
        '登录 / 注册',
        '手机号/邮箱',
        'please login again for security reasons',
    ]
    return any(sign in body_text for sign in bad_signs), body_text


async def navigate_to_target(page, url: str):
    print(f"[Navigate] 目标页: {url}")
    try:
        await page.goto(url, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"[Navigate] goto 超时/失败: {e}")
    await page.wait_for_timeout(8000)
    return await is_login_page(page)


async def try_cookie_context(p: async_playwright):
    """回退：用 .env 中的 Cookie。"""
    try:
        cookie_str = load_cookie()
    except RuntimeError:
        return None

    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(viewport={"width": 1800, "height": 1200})
    cookies = cookie_string_to_playwright(cookie_str)
    for c in cookies:
        c["domain"] = ".lanhuapp.com"
        c["path"] = "/"
    await context.add_cookies(cookies)
    print("[Cookie] 使用 .env Cookie")
    return context


async def main(url: str):
    tid, pid, image_id = parse_target_from_url(url)
    print(f"[Target] tid={tid} pid={pid} image_id={image_id}")

    async with async_playwright() as p:
        # Step 1: 优先用 Chrome 会话
        context = await try_chrome_context(p)
        if not context:
            context = await try_cookie_context(p)
        if not context:
            raise RuntimeError("无法建立任何有效会话")

        await dump_cookie_names(context)
        page = await context.new_page()

        # Step 2: 直接访问目标 detailDetach URL
        target_url = build_detail_detach_url(tid, pid, image_id)

        is_login, body_text = await navigate_to_target(page, target_url)
        print(f"[URL] 当前: {page.url}")
        print(f"[Body] {body_text[:300].replace(chr(10), ' ')}")

        if is_login:
            print("[Error] 仍然被导向登录页，尝试 SSO 流程...")
            # SSO 获取 sso_token
            sso_url = build_sso_url(tid, pid, image_id)

            print(f"[SSO] 访问: {sso_url}")
            try:
                await page.goto(sso_url, wait_until="networkidle", timeout=30000)
            except Exception as e:
                print(f"[SSO] goto 超时/失败: {e}")
            await page.wait_for_timeout(5000)

            # 从 URL 中提取 sso_token
            final_url = page.url
            sso_token = None
            if "sso_token=" in final_url:
                parsed = urllib.parse.urlparse(final_url)
                qs = urllib.parse.parse_qs(parsed.query)
                tokens = qs.get("sso_token", [])
                if tokens:
                    sso_token = tokens[0]

            print(f"[Token] sso_token: {sso_token[:30] + '...' if sso_token else '未获取到'}")

            # 拼装带 sso_token 的 detailDetach URL
            detail_url = build_detail_url_with_sso(tid, pid, image_id, sso_token)

            is_login, body_text = await navigate_to_target(page, detail_url)
            print(f"[URL] 当前: {page.url}")
            print(f"[Body] {body_text[:300].replace(chr(10), ' ')}")

        if is_login:
            print("[Fatal] 仍然无法进入标注页，登录态失效")
            await context.close()
            raise RuntimeError("登录态失效，无法进入蓝湖标注页")

        # Step 3: 调试 API 权限
        await debug_lanhu_api(page)

        # Step 4: 提取标注面板 DOM
        data = await page.evaluate(PANEL_EXTRACT_JS)
        OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        await context.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: fetch_annotation_panel.py <detailDetach_url>")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1]))
