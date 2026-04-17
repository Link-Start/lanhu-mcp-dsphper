#!/usr/bin/env python3
"""Playwright 方案：自动遍历蓝湖标注页所有控件，提取每个控件的标注面板数据。

前置条件：
    1. Chrome 已安装并可用（ playwright install chromium ）
    2. .env 中有有效 LANHU_COOKIE（或本机 Chrome 已登录）
    3. detailDetach URL 格式正确

用法：
    python3 fetch_all_annotations.py "<detailDetach_url>"

输出：
    /tmp/lanhu_all_annotations.json   # 所有控件标注数据数组
    /tmp/lanhu_all_annotations.txt   # 人类可读表格格式
"""

import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

OUT_JSON = Path("/tmp/lanhu_all_annotations.json")
OUT_TXT = Path("/tmp/lanhu_all_annotations.txt")

# Chrome 配置（从 fetch_annotation_panel.py 复用）
CHROME_USER_DATA_DIR = "/Users/link/Library/Application Support/Google/Chrome"
CHROME_PROFILE_DIR = "Profile 4"
ENV_PATH = Path("/Users/link/Desktop/lanhu-mcp/.env")

DEFAULT_TID = "a62f8ede-71ee-490b-85df-667e49159227"
DEFAULT_PID = "922b49c9-d582-462f-80dd-e4ceac466e4b"
DEFAULT_IMAGE_ID = "1b172705-b429-445e-8ad7-9764ae4471df"


# ============================================================================
# 从 fetch_chrome_dom.py 复用的正则解析函数
# ============================================================================

def extract_from_text(panel_text: str) -> dict:
    """从标注面板文本提取所有属性。"""
    result = {}

    # --- 平台选择器 ---
    platform_options = re.findall(r'(iOS|Android|Web|微信小程序)', panel_text)
    platform_options = list(dict.fromkeys(platform_options))
    result['platform_options'] = platform_options

    # 当前选中平台
    m_scale = re.search(r'(iOS|Android|Web|微信小程序)\s+@([0-9.]+)x', panel_text)
    if m_scale:
        result['current_platform'] = m_scale.group(1)
        result['device_scale'] = '@' + m_scale.group(2) + 'x'

    # 设计像素尺寸
    m_design = re.search(r'([0-9]+)px\s*[x×]\s*([0-9]+)px', panel_text)
    if m_design:
        result['design_pixel_size'] = {
            'width': m_design.group(1) + 'px',
            'height': m_design.group(2) + 'px'
        }

    # iOS Canvas pt 尺寸
    if result.get('device_scale') == '@2x' and m_design:
        w = int(m_design.group(1)) / 2
        h = int(m_design.group(2)) / 2
        result['canvas_pt'] = {'width': str(w) + 'pt', 'height': str(h) + 'pt', 'platform': 'iOS', 'scale': '2x'}
    elif result.get('device_scale') == '@3x' and m_design:
        w = int(m_design.group(1)) / 3
        h = int(m_design.group(2)) / 3
        result['canvas_pt'] = {'width': str(w) + 'pt', 'height': str(h) + 'pt', 'platform': 'iOS', 'scale': '3x'}

    # --- 样式信息 ---
    m = re.search(r'图层\s*\n+([^\n]+?)\n+位置', panel_text)
    if not m:
        m = re.search(r'图层\s+([^\s\n]+)', panel_text)
    if m:
        result['layer_name'] = m.group(1).strip()

    m = re.search(r'位置\s+([0-9.]+)pt\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'位置\s+([0-9.]+)\n+([0-9.]+)', panel_text)
    if m:
        result['position'] = {'x': m.group(1) + 'pt', 'y': m.group(2) + 'pt'}

    m = re.search(r'大小\s+([0-9.]+)pt\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'大小\s+([0-9.]+)\n+([0-9.]+)', panel_text)
    if m:
        result['size'] = {'width': m.group(1) + 'pt', 'height': m.group(2) + 'pt'}

    m = re.search(r'不透明度\s+([0-9.]+%)', panel_text)
    if m:
        result['opacity'] = m.group(1)

    # --- 文本信息 ---
    m = re.search(r'字体\s+([^\n]+)', panel_text)
    if m:
        result['font_family'] = m.group(1).strip()

    m = re.search(r'字重\s+(Regular|Medium|Bold|Semibold|Heavy|Light|Thin|[0-9]{2,3})', panel_text)
    if m:
        result['font_weight'] = m.group(1)

    m = re.search(r'对齐\s+(左对齐|右对齐|居中对齐|两端对齐)', panel_text)
    if m:
        result['text_align'] = m.group(1)

    m = re.search(r'字号\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'字号\s+([0-9.]+)', panel_text)
    if m:
        result['font_size'] = m.group(1) + 'pt'

    m = re.search(r'字间距\s+([0-9.]+)pt', panel_text)
    if m:
        result['letter_spacing'] = m.group(1) + 'pt'

    m = re.search(r'行高\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'行高\s+([0-9.]+)', panel_text)
    if m:
        result['line_height'] = m.group(1) + 'pt'

    m = re.search(r'内容\s*\n+([^\n]+)', panel_text)
    if m:
        result['content'] = m.group(1).strip()

    # --- 颜色 & 渐变 ---
    all_hex = re.findall(r'HEX\s*#?\s*?([0-9A-Fa-f]{6})', panel_text)
    all_hex = ['#' + h.upper() for h in all_hex]

    has_gradient_style = '颜色样式' in panel_text and '主色' in panel_text
    gradient_stops = re.findall(r'#([0-9A-Fa-f]{6})\s+(\d+)%', panel_text)

    if gradient_stops and len(gradient_stops) >= 2:
        result['gradient'] = {
            'type': 'multi-stop',
            'stops': [{'color': '#' + c.upper(), 'alpha': p + '%'} for c, p in gradient_stops]
        }
        result['text_color'] = '#' + gradient_stops[0][0].upper()
    elif has_gradient_style and len(all_hex) >= 2:
        result['text_color'] = all_hex[0] if all_hex else None
        result['gradient'] = {
            'type': 'simple',
            'start': all_hex[1] if len(all_hex) > 1 else None,
            'end': all_hex[2] if len(all_hex) > 2 else all_hex[1] if len(all_hex) > 1 else None,
            'raw': all_hex[:4]
        }
    elif len(all_hex) >= 2:
        result['text_color'] = all_hex[0]
    elif all_hex:
        result['text_color'] = all_hex[0]

    m_css_grad = re.search(r'linear-gradient\([^)]+\)', panel_text)
    if m_css_grad:
        result['gradient_css'] = m_css_grad.group(0)

    m_rgba = re.search(r'RGBA\s*\(?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,?\s*([\d.]*)\s*\)?', panel_text)
    if m_rgba:
        r, g, b = m_rgba.group(1), m_rgba.group(2), m_rgba.group(3)
        a = m_rgba.group(4) or '1'
        result['text_color_rgba'] = f'rgba({r},{g},{b},{a})'

    # --- 圆角 ---
    m_br = re.search(r'圆角\s+([0-9.]+)pt', panel_text)
    if m_br:
        result['border_radius'] = m_br.group(1) + 'pt'
    m_br_px = re.search(r'圆角\s+([0-9.]+)px', panel_text)
    if m_br_px:
        result['border_radius'] = m_br_px.group(1) + 'px'

    # --- 阴影 ---
    for p in [
        r'阴影\s+([\d.]+\s*(?:px|pt)\s*){1,4}',
        r'阴影\n([^\n]+?)(?=\n[^ ]|历史版本|$)',
    ]:
        m = re.search(p, panel_text)
        if m:
            val = m.group(0).replace('阴影', '').strip()
            if val:
                result['shadow'] = val
                break

    # --- 边距 ---
    m_pad = re.search(r'边距\s+([0-9.]+)pt', panel_text)
    if m_pad:
        result['padding'] = m_pad.group(1) + 'pt'

    # --- 切片 ---
    m_slice = re.search(r'切片\s*\n+([^\n]+)', panel_text)
    if m_slice:
        result['slice_url'] = m_slice.group(1).strip()

    # --- 代码区 ---
    code_start = panel_text.find('代码')
    if code_start != -1:
        code_text = panel_text[code_start:]
        for lang in ['Objective-C', 'Swift', 'Java', 'Kotlin', 'XML', 'CSS', 'Python']:
            if lang in code_text:
                result['code_lang'] = lang
                break
        m_ui = re.search(r'UILabel\s*\*[^{]+', code_text)
        if m_ui:
            result['code_ios_label'] = m_ui.group(0).strip()
        m_swift = re.search(r'let\s+\w+\s*=\s*UILabel\(\)', code_text)
        if m_swift:
            result['code_ios_swift'] = 'Swift UILabel'
        m_view = re.search(r'UIView\s*\*[^{]+', code_text)
        if m_view:
            result['code_ios_view'] = m_view.group(0).strip()
        m_attr = re.search(r'NSMutableAttributedString[^{]+', code_text)
        if m_attr:
            result['code_ios_attributed'] = m_attr.group(0).strip()

    # --- 辅助字段 ---
    result['pt_snippets'] = re.findall(r'[0-9.]+\s*pt', panel_text)
    result['dp_snippets'] = re.findall(r'[0-9.]+\s*dp', panel_text)
    result['px_snippets'] = re.findall(r'[0-9.]+\s*px', panel_text)

    return result


# ============================================================================
# Playwright 上下文初始化（从 fetch_annotation_panel.py 复用）
# ============================================================================

async def try_chrome_context(p) -> Optional:
    """尝试复用本机 Chrome 已登录会话（复制临时目录）。"""
    chrome_root = Path(CHROME_USER_DATA_DIR)
    profile_dir = chrome_root / CHROME_PROFILE_DIR
    if not chrome_root.exists() or not profile_dir.exists():
        print(f"[Chrome] 目录不存在: {chrome_root} / {profile_dir}")
        return None

    temp_root = Path(tempfile.mkdtemp(prefix="lanhu-anno-"))
    temp_profile = temp_root / CHROME_PROFILE_DIR
    temp_profile.mkdir(parents=True, exist_ok=True)

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

    try:
        context = await p.chromium.launch_persistent_context(
            str(temp_root),
            channel="chrome",
            headless=False,
            viewport={"width": 1800, "height": 1200},
            args=["--no-first-run", "--disable-background-timer-throttling",
                  f"--profile-directory={CHROME_PROFILE_DIR}"],
        )
        print(f"[Chrome] 成功复用 Profile={CHROME_PROFILE_DIR}")
        return context
    except Exception as e:
        print(f"[Chrome] 启动失败: {e}")
        return None


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


async def try_cookie_context(p) -> Optional:
    """回退：用 .env 中的 Cookie。"""
    try:
        cookie_str = load_cookie()
    except RuntimeError:
        return None

    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context(viewport={"width": 1800, "height": 1200})
    cookies = cookie_string_to_playwright(cookie_str)
    for c in cookies:
        c["domain"] = ".lanhuapp.com"
        c["path"] = "/"
    await context.add_cookies(cookies)
    print("[Cookie] 使用 .env Cookie")
    return context


# ============================================================================
# URL 解析与导航
# ============================================================================

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


async def is_login_page(page) -> tuple:
    body_text = await page.evaluate(
        "document.body ? document.body.innerText.slice(0, 2000) : ''"
    )
    bad_signs = [
        '欢迎来到蓝湖', '登录 / 注册', '手机号/邮箱',
        'please login again for security reasons',
    ]
    return any(s in body_text for s in bad_signs), body_text


# ============================================================================
# 核心：自动遍历脚本（注入页面的 JS）
# ============================================================================

# 注入蓝湖页面的 JS：
# 1. 找到 __vue__ 实例，读取 g_detail.layers 拿到所有图层元数据
# 2. 遍历 .layers_item，点击每个控件，触发标注面板更新
# 3. 每次点击后用 MutationObserver 等 200ms 等待面板稳定
# 4. 提取面板文本区域（到"历史版本"之前的 innerText）
# 5. 返回所有控件的 {name, index, annotation_panel_text, vue_layer_info}
LANHU_AUTO_TRAVERSE_JS = r"""
(async () => {
  // 1. 找到 Vue 实例
  var el = document.querySelector('.layer_interactive');
  var vm = null;
  var node = el;
  while (node) { if (node.__vue__) { vm = node.__vue__; break; } node = node.parentElement; }
  var layers = vm && vm.g_detail && vm.g_detail.layers;

  // 2. 找到所有可点击图层项
  var items = Array.from(document.querySelectorAll('.layers_item'));

  // 3. 辅助：从 body innerText 截取到"历史版本"之前的区域
  function getPanelText() {
    var t = document.body ? document.body.innerText : '';
    var end = t.indexOf('历史版本');
    if (end === -1) end = t.length;
    return t.slice(0, end);
  }

  // 4. 遍历点击每个图层项，等待面板更新后提取文本
  var results = [];
  for (var i = 1; i < items.length; i++) {
    var item = items[i];
    var L = layers && layers[i];

    // 跳过不可见或尺寸为0的元素（从Vue层数据判断）
    if (L && (L.visible === false || (!L.width && !L.height))) continue;

    // 派发鼠标事件选中控件
    item.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:100, clientY:100}));
    item.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    item.dispatchEvent(new MouseEvent('click', {bubbles:true}));

    // 等待面板更新（200ms 足够）
    await new Promise(r => setTimeout(r, 200));

    var panelText = getPanelText();
    var layerInfo = L ? {
      name: L.name || '',
      type: L.type || '',
      left: L.left || 0,
      top: L.top || 0,
      width: L.width || 0,
      height: L.height || 0,
      images: L.images || {}
    } : null;

    results.push({
      index: i,
      layer_name: layerInfo ? layerInfo.name : ('layer_' + i),
      layer_type: layerInfo ? layerInfo.type : '',
      vue_left: layerInfo ? layerInfo.left : null,
      vue_top: layerInfo ? layerInfo.top : null,
      vue_width: layerInfo ? layerInfo.width : null,
      vue_height: layerInfo ? layerInfo.height : null,
      vue_images: layerInfo ? layerInfo.images : {},
      panel_text: panelText
    });
  }

  return JSON.stringify(results);
})()
"""


# ============================================================================
# 主流程
# ============================================================================

async def main(url: str):
    tid, pid, image_id = parse_target_from_url(url)
    print(f"[Target] tid={tid} pid={pid} image_id={image_id}")

    async with async_playwright() as p:
        # 建立会话（优先 Chrome 会话，回退 Cookie）
        context = await try_chrome_context(p)
        if not context:
            context = await try_cookie_context(p)
        if not context:
            print("[Fatal] 无法建立任何有效会话")
            raise RuntimeError("无法建立任何有效会话")

        page = await context.new_page()

        # 导航到 detailDetach
        target_url = build_detail_detach_url(tid, pid, image_id)
        print(f"[Navigate] {target_url}")
        try:
            await page.goto(target_url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"[Navigate] 超时: {e}")
        await page.wait_for_timeout(5000)

        is_login, body_text = await is_login_page(page)
        if is_login:
            print("[Login] 被导向登录页，登录态失效")
            print(f"[Body] {body_text[:300]}")
            await context.close()
            raise RuntimeError("登录态失效，无法进入标注页")

        print("[Status] 页面加载完成，等待标注面板可用...")
        await page.wait_for_timeout(3000)

        # 注入并执行自动遍历 JS
        print("[Traverse] 开始自动遍历所有控件...")
        print("[Traverse] 这一步可能需要 30-90 秒，请耐心等待...")

        result_text = await page.evaluate(LANHU_AUTO_TRAVERSE_JS)

        # 解析层数据
        try:
            layer_results = json.loads(result_text)
        except Exception as e:
            print(f"[Error] 解析 JS 返回失败: {e}")
            print(f"[Raw] {result_text[:500]}")
            layer_results = []

        print(f"[Traverse] 获取到 {len(layer_results)} 个控件，开始解析标注...")

        # 解析每个控件的标注面板文本
        all_annotations = []
        for item in layer_results:
            panel_text = item.get('panel_text', '')
            parsed = extract_from_text(panel_text)

            # 合并 Vue 层数据和标注数据
            entry = {
                'index': item.get('index'),
                'layer_name': item.get('layer_name'),
                'layer_type': item.get('layer_type'),
                'vue_left_pt': round(item.get('vue_left', 0) / 2, 1) if item.get('vue_left') else None,
                'vue_top_pt': round(item.get('vue_top', 0) / 2, 1) if item.get('vue_top') else None,
                'vue_width_pt': round(item.get('vue_width', 0) / 2, 1) if item.get('vue_width') else None,
                'vue_height_pt': round(item.get('vue_height', 0) / 2, 1) if item.get('vue_height') else None,
            }

            # 图层来源优先级：正则解析的图层名 > Vue 里的 name
            if parsed.get('layer_name'):
                entry['layer_name'] = parsed['layer_name']
            if parsed.get('position'):
                entry['position'] = parsed['position']
            if parsed.get('size'):
                entry['size'] = parsed['size']

            # 复制所有解析出的字段
            for key in ['platform_options', 'current_platform', 'device_scale',
                        'design_pixel_size', 'canvas_pt', 'opacity',
                        'font_family', 'font_weight', 'text_align',
                        'font_size', 'line_height', 'letter_spacing', 'content',
                        'text_color', 'text_color_rgba', 'gradient', 'gradient_css',
                        'border_radius', 'shadow', 'padding', 'slice_url',
                        'code_lang', 'code_ios_label', 'code_ios_attributed',
                        'pt_snippets', 'dp_snippets', 'px_snippets']:
                if key in parsed:
                    entry[key] = parsed[key]

            all_annotations.append(entry)

        # 保存 JSON
        OUT_JSON.write_text(json.dumps(all_annotations, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] JSON 已保存: {OUT_JSON}")

        # 生成人类可读文本
        lines = []
        lines.append("=== 蓝湖标注面板 — 全部控件遍历结果 ===\n")
        for i, item in enumerate(all_annotations):
            lines.append(f"\n--- [{i+1}] {item.get('layer_name', '?')} ({item.get('layer_type', '?')}) ---")
            if item.get('position'):
                p = item['position']
                lines.append(f"  位置: x={p['x']}  y={p['y']}")
            if item.get('size'):
                s = item['size']
                lines.append(f"  大小: {s['width']} × {s['height']}")
            if item.get('vue_left_pt') is not None:
                lines.append(f"  Vue坐标(px→pt): left={item['vue_left_pt']}pt  top={item['vue_top_pt']}pt")
                lines.append(f"  Vue尺寸(px→pt): {item['vue_width_pt']}pt × {item['vue_height_pt']}pt")
            if item.get('font_family'):
                lines.append(f"  字体: {item['font_family']}  {item.get('font_weight', '')}")
            if item.get('font_size'):
                lines.append(f"  字号: {item['font_size']}  行高: {item.get('line_height', '?')}  字间距: {item.get('letter_spacing', '?')}")
            if item.get('text_color'):
                lines.append(f"  颜色: {item['text_color']}  RGBA: {item.get('text_color_rgba', '?')}")
            if item.get('gradient'):
                lines.append(f"  渐变: {item['gradient']}")
            if item.get('border_radius'):
                lines.append(f"  圆角: {item['border_radius']}")
            if item.get('shadow'):
                lines.append(f"  阴影: {item['shadow']}")
            if item.get('content'):
                lines.append(f"  内容: {item['content']}")
            if item.get('text_align'):
                lines.append(f"  对齐: {item['text_align']}")
            if item.get('opacity'):
                lines.append(f"  不透明度: {item['opacity']}")
            if item.get('code_lang'):
                lines.append(f"  代码: {item['code_lang']}")

        OUT_TXT.write_text('\n'.join(lines), encoding="utf-8")
        print(f"[OK] TXT 已保存: {OUT_TXT}")

        # 统计摘要
        has_pos = sum(1 for i in all_annotations if i.get('position'))
        has_color = sum(1 for i in all_annotations if i.get('text_color'))
        has_font = sum(1 for i in all_annotations if i.get('font_family'))
        has_grad = sum(1 for i in all_annotations if i.get('gradient'))
        has_br = sum(1 for i in all_annotations if i.get('border_radius'))
        print(f"\n=== 统计摘要 ===")
        print(f"  总控件数: {len(all_annotations)}")
        print(f"  有位置信息: {has_pos}")
        print(f"  有颜色信息: {has_color}")
        print(f"  有字体信息: {has_font}")
        print(f"  有渐变信息: {has_grad}")
        print(f"  有圆角信息: {has_br}")

        await context.close()
        return all_annotations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 fetch_all_annotations.py \"<detailDetach_url>\"")
        print(f"默认使用: https://lanhuapp.com/web/#/item/project/detailDetach?tid={DEFAULT_TID}&pid={DEFAULT_PID}&image_id={DEFAULT_IMAGE_ID}")
        default_url = build_detail_detach_url(DEFAULT_TID, DEFAULT_PID, DEFAULT_IMAGE_ID)
        print(f"\n使用默认 URL 继续...")
        url = default_url
    else:
        url = sys.argv[1]

    asyncio.run(main(url))