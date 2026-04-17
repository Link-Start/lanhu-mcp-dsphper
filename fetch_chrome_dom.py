#!/usr/bin/env python3
"""用 AppleScript 从已打开的 Chrome 蓝湖标注页抓取完整右侧面板数据。

前置条件：
    Chrome → 查看 → 开发者 → 允许 Apple 事件中的 JavaScript（打勾）

用法：
    python3 fetch_chrome_dom.py [detailDetach_url]

提取内容：
    ✅ 顶部平台选择器（iOS/Android/Web/微信小程序）
    ✅ Canvas 尺寸
    ✅ 样式信息（图层/位置/大小/不透明度）
    ✅ 文本信息（字体/字重/对齐/字号/行高/字间距/颜色）
    ✅ 渐变信息（如有）
    ✅ 圆角（如有）
    ✅ 阴影信息（如有）
    ✅ 边距（如有）
    ✅ 代码区（Objective-C / Swift / XML / CSS）
    ❌ 内容（仅文本元素有）

输出：/tmp/lanhu_panel_data.json
"""

import json
import re
import subprocess
import sys
from pathlib import Path

OUT_PATH = Path("/tmp/lanhu_panel_data.json")


def extract_from_text(panel_text: str) -> dict:
    """从标注面板文本提取所有属性。"""
    result = {}

    # --- 平台选择器 ---
    # body innerText 中有 "选择开发平台" + iOS/Android/Web/微信小程序 选项
    platform_options = re.findall(r'(iOS|Android|Web|微信小程序)', panel_text)
    platform_options = list(dict.fromkeys(platform_options))  # 去重保留顺序
    result['platform_options'] = platform_options

    # 当前选中平台（标注视图右上角显示的那个）
    # iOS @2x / @3x 等 scale 标注
    m_scale = re.search(r'(iOS|Android|Web|微信小程序)\s+@([0-9.]+)x', panel_text)
    if m_scale:
        result['current_platform'] = m_scale.group(1)
        result['device_scale'] = '@' + m_scale.group(2) + 'x'

    # 设计像素尺寸（如 750px × 1812px）
    m_design = re.search(r'([0-9]+)px\s*[x×]\s*([0-9]+)px', panel_text)
    if m_design:
        result['design_pixel_size'] = {'width': m_design.group(1) + 'px', 'height': m_design.group(2) + 'px'}

    # iOS Canvas pt 尺寸（从 API 或 scale 计算，但 innerText 里可能无直接文本）
    # 从 scale 推断
    if result.get('device_scale') == '@2x' and m_design:
        w = int(m_design.group(1)) / 2
        h = int(m_design.group(2)) / 2
        result['canvas_pt'] = {'width': str(w) + 'pt', 'height': str(h) + 'pt', 'platform': 'iOS', 'scale': '2x'}
    elif result.get('device_scale') == '@3x' and m_design:
        w = int(m_design.group(1)) / 3
        h = int(m_design.group(2)) / 3
        result['canvas_pt'] = {'width': str(w) + 'pt', 'height': str(h) + 'pt', 'platform': 'iOS', 'scale': '3x'}

    # --- 样式信息 ---
    # 图层名
    m = re.search(r'图层\s*\n+([^\n]+?)\n+位置', panel_text)
    if not m:
        m = re.search(r'图层\s+([^\s\n]+)', panel_text)
    if m:
        result['layer_name'] = m.group(1).strip()

    # 位置
    m = re.search(r'位置\s+([0-9.]+)pt\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'位置\s+([0-9.]+)\n+([0-9.]+)', panel_text)
    if m:
        result['position'] = {'x': m.group(1) + 'pt', 'y': m.group(2) + 'pt'}

    # 大小
    m = re.search(r'大小\s+([0-9.]+)pt\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'大小\s+([0-9.]+)\n+([0-9.]+)', panel_text)
    if m:
        result['size'] = {'width': m.group(1) + 'pt', 'height': m.group(2) + 'pt'}

    # 不透明度
    m = re.search(r'不透明度\s+([0-9.]+%)', panel_text)
    if m:
        result['opacity'] = m.group(1)

    # --- 文本信息 ---
    # 字体
    m = re.search(r'字体\s+([^\n]+)', panel_text)
    if m:
        result['font_family'] = m.group(1).strip()

    # 字重
    m = re.search(r'字重\s+(Regular|Medium|Bold|Semibold|Heavy|Light|Thin|[0-9]{2,3})', panel_text)
    if m:
        result['font_weight'] = m.group(1)

    # 对齐
    m = re.search(r'对齐\s+(左对齐|右对齐|居中对齐|两端对齐)', panel_text)
    if m:
        result['text_align'] = m.group(1)

    # 字号
    m = re.search(r'字号\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'字号\s+([0-9.]+)', panel_text)
    if m:
        result['font_size'] = m.group(1) + 'pt'

    # 字间距
    m = re.search(r'字间距\s+([0-9.]+)pt', panel_text)
    if m:
        result['letter_spacing'] = m.group(1) + 'pt'

    # 行高
    m = re.search(r'行高\s+([0-9.]+)pt', panel_text)
    if not m:
        m = re.search(r'行高\s+([0-9.]+)', panel_text)
    if m:
        result['line_height'] = m.group(1) + 'pt'

    # 内容（标注文字内容）
    m = re.search(r'内容\s*\n+([^\n]+)', panel_text)
    if m:
        result['content'] = m.group(1).strip()

    # --- 颜色 & 渐变 ---
    # 先收集所有 HEX 值（支持换行，支持 HEX\nHEX#xxxxxx 格式）
    all_hex = re.findall(r'HEX\s*#?\s*?([0-9A-Fa-f]{6})', panel_text)
    all_hex = ['#' + h.upper() for h in all_hex]

    # 判断是否为渐变：存在 "颜色样式" 块（含主色） + "颜色" 块（含多个色值）
    has_gradient_style = '颜色样式' in panel_text and '主色' in panel_text

    # 检测多色渐变（带百分比透明度/Alpha）
    # 格式如: #2D2C2C 0%  HEX\n #2C2C2C 52%  HEX\n ...
    gradient_stops = re.findall(r'#([0-9A-Fa-f]{6})\s+(\d+)%', panel_text)
    if gradient_stops and len(gradient_stops) >= 2:
        result['gradient'] = {
            'type': 'multi-stop',
            'stops': [{'color': '#' + c.upper(), 'alpha': p + '%'} for c, p in gradient_stops]
        }
        result['text_color'] = '#' + gradient_stops[0][0].upper()
    elif has_gradient_style and len(all_hex) >= 2:
        # 取颜色样式块的主色（第1个）
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
        # 语言
        for lang in ['Objective-C', 'Swift', 'Java', 'Kotlin', 'XML', 'CSS', 'Python']:
            if lang in code_text:
                result['code_lang'] = lang
                break
        # UILabel
        m_ui = re.search(r'UILabel\s*\*[^{]+', code_text)
        if m_ui:
            result['code_ios_label'] = m_ui.group(0).strip()
        # Swift UILabel
        m_swift = re.search(r'let\s+\w+\s*=\s*UILabel\(\)', code_text)
        if m_swift:
            result['code_ios_swift'] = 'Swift UILabel'
        # Android View
        m_view = re.search(r'UIView\s*\*[^{]+', code_text)
        if m_view:
            result['code_ios_view'] = m_view.group(0).strip()
        # NSAttributedString
        m_attr = re.search(r'NSMutableAttributedString[^{]+', code_text)
        if m_attr:
            result['code_ios_attributed'] = m_attr.group(0).strip()

    # --- 全部 pt/dp/px 片段 ---
    result['pt_snippets'] = re.findall(r'[0-9.]+\s*pt', panel_text)
    result['dp_snippets'] = re.findall(r'[0-9.]+\s*dp', panel_text)
    result['px_snippets'] = re.findall(r'[0-9.]+\s*px', panel_text)

    return result


def run_applescript() -> str:
    """提取从页面顶部到历史版本之间的完整文本（含平台选择器 + 样式信息 + 代码）。"""
    js_code = """
(function(){
    var t = document.body ? document.body.innerText : '';
    var end = t.indexOf('历史版本');
    if (end === -1) end = t.length;
    return t.slice(0, end);
})()
"""
    escaped = js_code.replace('\\', '\\\\').replace('"', '\\"')
    script = f'''
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t) contains "detailDetach" then
                set jsResult to execute t javascript "{escaped}"
                return jsResult
            end if
        end repeat
    end repeat
    return "NOT_FOUND"
end tell
'''
    result = subprocess.run(
        ['osascript', '-'],
        input=script.encode('utf-8'),
        capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript error: {result.stderr.decode('utf-8', errors='replace')}")
    raw = result.stdout.decode('utf-8', errors='replace').strip()
    return raw


def run_platform_selector_js() -> dict:
    """直接查 DOM 获取当前平台选择器状态。"""
    js_code = """
(function(){
    var result = {current: null, options: []};

    // 找当前选中平台的文本
    var all = Array.from(document.querySelectorAll('*'));
    var platformMap = {
        'iOS': 'iOS',
        'Android': 'Android',
        'Web': 'Web',
        '微信小程序': '微信小程序'
    };

    // 找顶部平台切换区的文本（mu-dropDown-menu 类附近）
    all.forEach(function(el){
        var t = (el.className || '');
        if (t.indexOf('mu-select-field') !== -1 || t.indexOf('mu-dropDown') !== -1) {
            var txt = (el.textContent || '').trim();
            if (txt && platformMap[txt]) {
                result.current = txt;
            }
        }
    });

    // 找 canvas 尺寸（iOS / Android / Web / 微信小程序 xxx x xxx）
    var canvasEls = Array.from(document.querySelectorAll('*'))
        .filter(function(el){
            var t = (el.textContent || '').trim();
            return /^(iOS|Android|Web|微信小程序)\s+\d+\s*[x×]\s*\d+\s*(pt|dp|px|rpx)/.test(t);
        });
    result.canvasInfo = canvasEls.map(function(el){ return (el.textContent||'').trim(); });

    // 找代码语言
    var codeEls = Array.from(document.querySelectorAll('*'))
        .filter(function(el){
            var t = (el.textContent||'').trim();
            return t === 'Objective-C' || t === 'Swift' || t === 'Java' || t === 'Kotlin' || t === 'XML' || t === 'CSS' || t === 'Python';
        });
    result.codeLangs = codeEls.map(function(el){ return (el.textContent||'').trim(); });

    return JSON.stringify(result);
})()
"""
    escaped = js_code.replace('\\', '\\\\').replace('"', '\\"')
    script = f'''
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t) contains "detailDetach" then
                set jsResult to execute t javascript "{escaped}"
                return jsResult
            end if
        end repeat
    end repeat
    return "NOT_FOUND"
end tell
'''
    result = subprocess.run(
        ['osascript', '-'],
        input=script.encode('utf-8'),
        capture_output=True
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout.decode('utf-8', errors='replace').strip())
    except:
        return {}


def main():
    if len(sys.argv) >= 2:
        target_url = sys.argv[1]
    else:
        target_url = "(任意 detailDetach URL)"

    print(f"[Info] 目标: {target_url}")
    print(f"[Info] 输出: {OUT_PATH}")

    # Step 1: 获取面板文本（含顶部平台选择器 + 样式信息 + 代码区）
    raw = run_applescript()
    if raw == "NOT_FOUND" or not raw:
        print("[Error] 未找到打开的 detailDetach 标签页")
        sys.exit(1)

    print(f"[Info] 面板文本长度: {len(raw)} 字符")

    # Step 2: 正则解析所有字段
    data = extract_from_text(raw)

    # Step 3: 获取当前平台选择器（DOM 方式补充）
    platform_info = run_platform_selector_js()
    if platform_info and platform_info.get('current'):
        data['current_platform'] = platform_info['current']

    # 输出
    print("\n=== 蓝湖标注面板数据 ===")
    print(f"  平台选项: {data.get('platform_options', [])}")
    print(f"  当前平台: {data.get('current_platform', '?')}")
    print(f"  设计像素尺寸: {data.get('design_pixel_size', '?')}")
    if data.get('canvas_pt'):
        c = data['canvas_pt']
        print(f"  Canvas(pt): {c['width']} × {c['height']} ({c['platform']} {c['scale']})")
    print(f"  图层名: {data.get('layer_name', '?')}")
    if data.get('position'):
        print(f"  位置: x={data['position']['x']} y={data['position']['y']}")
    if data.get('size'):
        print(f"  大小: width={data['size']['width']} height={data['size']['height']}")
    print(f"  不透明度: {data.get('opacity', '?')}")
    print(f"  字体: {data.get('font_family', '?')}")
    print(f"  字重: {data.get('font_weight', '?')}")
    print(f"  对齐: {data.get('text_align', '?')}")
    print(f"  字号: {data.get('font_size', '?')}")
    print(f"  行高: {data.get('line_height', '?')}")
    print(f"  字间距: {data.get('letter_spacing', '?')}")
    print(f"  颜色: {data.get('text_color', '?')}")
    if data.get('gradient') and isinstance(data['gradient'], dict):
        g = data['gradient']
        if g.get('type') == 'multi-stop':
            stops = g.get('stops', [])
            print(f"  渐变: {len(stops)} 色渐变")
            for s in stops:
                print(f"    - {s['color']}  透明度:{s['alpha']}")
        elif g.get('type') == 'simple':
            print(f"  渐变: {g.get('start')} → {g.get('end')}")
        else:
            print(f"  渐变: {g}")
    elif data.get('gradient'):
        print(f"  渐变: {data.get('gradient')}")
    if data.get('gradient_css'):
        print(f"  渐变CSS: {data.get('gradient_css')}")
    if data.get('border_radius'):
        print(f"  圆角: {data.get('border_radius')}")
    if data.get('shadow'):
        print(f"  阴影: {data.get('shadow')}")
    if data.get('padding'):
        print(f"  边距: {data.get('padding')}")
    print(f"  内容: {data.get('content', '?')}")
    print(f"  代码语言: {data.get('code_lang', '?')}")
    if data.get('code_ios_label'):
        print(f"  iOS UILabel: ✅")
    if data.get('code_ios_attributed'):
        print(f"  iOS NSAttributedString: ✅")

    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 已保存到 {OUT_PATH}")
    return data


if __name__ == "__main__":
    main()
