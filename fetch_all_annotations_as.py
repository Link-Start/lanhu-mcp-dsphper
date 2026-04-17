#!/usr/bin/env python3
"""AppleScript 方案（修正版）：自动遍历蓝湖标注页所有控件。

核心修复：
    AppleScript 的 execute javascript 不支持 async/await，
    也不能用阻塞循环代替 setTimeout（JS 是单线程的）。
    解决：Python 端控制节奏，JS 只做两件事：点击 或 读纯文本。

前置条件：
    Chrome → 查看 → 开发者 → 允许 Apple 事件中的 JavaScript
    蓝湖标注页已在 Chrome 打开，用户已选中任意控件
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

OUT_JSON = Path("/tmp/lanhu_all_annotations.json")
OUT_TXT = Path("/tmp/lanhu_all_annotations.txt")

# 等待时间（秒）- 面板 DOM 更新需要的时间
PANEL_WAIT = 0.4


# ============================================================================
# AppleScript 执行核心
# ============================================================================

def run_js(js_code: str) -> str:
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
    result = subprocess.run(['osascript', '-'], input=script.encode('utf-8'), capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode())
    return result.stdout.decode('utf-8', errors='replace').strip()


# ============================================================================
# 两个 JS 函数（必须分离，不含任何 async/await/setTimeout）
# ============================================================================

# JS-A: 点击第 idx 个 .layers_item（纯同步，无返回值）
CLICK_JS_TEMPLATE = r"""
(function(){{
    var items = document.querySelectorAll('.layers_item');
    if (!items || items.length === 0) return;
    var idx = {idx};
    if (idx < 0 || idx >= items.length) return;
    var item = items[idx];
    item.dispatchEvent(new MouseEvent('mousedown', {{bubbles:true, clientX:100, clientY:100}}));
    item.dispatchEvent(new MouseEvent('mouseup', {{bubbles:true}}));
    item.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
}})()
"""

# JS-B: 读取标注面板纯文本（纯同步）
GET_PANEL_JS = r"""
(function(){
    var t = document.body ? document.body.innerText : '';
    var end = t.indexOf('历史版本');
    if (end === -1) end = t.length;
    return t.slice(0, end);
})()
"""


# ============================================================================
# 正则解析（与 fetch_chrome_dom.py 完全一致）
# ============================================================================

def extract_from_text(panel_text: str) -> dict:
    result = {}

    platform_options = re.findall(r'(iOS|Android|Web|微信小程序)', panel_text)
    result['platform_options'] = list(dict.fromkeys(platform_options))

    m_scale = re.search(r'(iOS|Android|Web|微信小程序)\s+@([0-9.]+)x', panel_text)
    if m_scale:
        result['current_platform'] = m_scale.group(1)
        result['device_scale'] = '@' + m_scale.group(2) + 'x'

    m_design = re.search(r'([0-9]+)px\s*[x×]\s*([0-9]+)px', panel_text)
    if m_design:
        result['design_pixel_size'] = {'width': m_design.group(1) + 'px', 'height': m_design.group(2) + 'px'}

    if result.get('device_scale') == '@2x' and m_design:
        result['canvas_pt'] = {
            'width': str(int(m_design.group(1)) / 2) + 'pt',
            'height': str(int(m_design.group(2)) / 2) + 'pt',
            'platform': 'iOS', 'scale': '2x'
        }
    elif result.get('device_scale') == '@3x' and m_design:
        result['canvas_pt'] = {
            'width': str(int(m_design.group(1)) / 3) + 'pt',
            'height': str(int(m_design.group(2)) / 3) + 'pt',
            'platform': 'iOS', 'scale': '3x'
        }

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

    # 颜色 & 渐变
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
        result['text_color'] = all_hex[0]
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
        result['text_color_rgba'] = f'rgba({m_rgba.group(1)},{m_rgba.group(2)},{m_rgba.group(3)},{m_rgba.group(4) or "1"})'

    m_br = re.search(r'圆角\s+([0-9.]+)pt', panel_text)
    if m_br:
        result['border_radius'] = m_br.group(1) + 'pt'
    m_br_px = re.search(r'圆角\s+([0-9.]+)px', panel_text)
    if m_br_px:
        result['border_radius'] = m_br_px.group(1) + 'px'

    for p in [r'阴影\s+([\d.]+\s*(?:px|pt)\s*){1,4}', r'阴影\n([^\n]+?)(?=\n[^ ]|历史版本|$)']:
        m = re.search(p, panel_text)
        if m:
            val = m.group(0).replace('阴影', '').strip()
            if val:
                result['shadow'] = val
                break

    m_pad = re.search(r'边距\s+([0-9.]+)pt', panel_text)
    if m_pad:
        result['padding'] = m_pad.group(1) + 'pt'

    m_slice = re.search(r'切片\s*\n+([^\n]+)', panel_text)
    if m_slice:
        result['slice_url'] = m_slice.group(1).strip()

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
        m_attr = re.search(r'NSMutableAttributedString[^{]+', code_text)
        if m_attr:
            result['code_ios_attributed'] = m_attr.group(0).strip()

    result['pt_snippets'] = re.findall(r'[0-9.]+\s*pt', panel_text)
    result['dp_snippets'] = re.findall(r'[0-9.]+\s*dp', panel_text)
    result['px_snippets'] = re.findall(r'[0-9.]+\s*px', panel_text)

    return result


# ============================================================================
# 主流程
# ============================================================================

def main():
    print("[1/3] 探测图层数量...")
    probe_js = r"""
    (function(){
        var items = document.querySelectorAll('.layers_item');
        return JSON.stringify({total: items ? items.length : 0});
    })()
    """
    raw = run_js(probe_js)
    if raw == "NOT_FOUND":
        print("[Error] 未找到 detailDetach 标签页")
        sys.exit(1)
    try:
        probe = json.loads(raw)
    except Exception as e:
        print(f"[Error] 解析探测结果失败: {e}")
        sys.exit(1)

    total = probe.get('total', 0)
    print(f"[Info] .layers_item 总数: {total}")
    if total == 0:
        print("[Error] 未找到任何图层元素")
        sys.exit(1)

    print(f"\n[2/3] 开始遍历 {total} 个控件...")
    print(f"[     ] 每个控件等待 {PANEL_WAIT}s，预计需要 {total * PANEL_WAIT:.0f}s")
    print("[     ] 按 Ctrl+C 可中途停止，已抓取的会保留\n")

    all_annotations = []
    last_name = '(初始)'

    for idx in range(total):
        # Step A: 点击
        click_js = CLICK_JS_TEMPLATE.format(idx=idx)
        run_js(click_js)

        # Step B: 等待面板更新（Python 端控制）
        time.sleep(PANEL_WAIT)

        # Step C: 读取面板文本
        panel_text = run_js(GET_PANEL_JS)
        if panel_text == "NOT_FOUND" or not panel_text:
            print(f"[{idx+1}/{total}] ⚠️ 标签页关闭")
            break

        # 判断是否真的是"标注"内容（而非登录提示等）
        panel_len = len(panel_text)
        is_annotating = (
            panel_len > 300 and
            ('图层' in panel_text or '位置' in panel_text) and
            '历史版本' not in panel_text  # 还没到历史版本就截断了
        )

        parsed = extract_from_text(panel_text)

        entry = {
            'seq': len(all_annotations) + 1,
            'idx': idx,
            'panel_len': panel_len,
            'is_annotating': is_annotating,
            'layer_name': parsed.get('layer_name', f'item_{idx}'),
        }

        if parsed.get('layer_name'):
            entry['layer_name'] = parsed['layer_name']
        if parsed.get('position'):
            entry['position'] = parsed['position']
        if parsed.get('size'):
            entry['size'] = parsed['size']

        # 合并其他字段
        skip_keys = {'seq', 'idx', 'panel_len', 'is_annotating', 'layer_name', 'position', 'size'}
        for key, val in parsed.items():
            if key not in skip_keys:
                entry[key] = val

        all_annotations.append(entry)

        # 进度
        name = entry['layer_name'] or f'item_{idx}'
        marker = ""
        if parsed.get('gradient'):
            marker += " 🎨"
        if parsed.get('border_radius'):
            marker += " ⬜"
        if parsed.get('text_color') and not parsed.get('gradient'):
            marker += f" #{parsed.get('text_color')}"
        print(f"[{idx+1}/{total}] {name[:40]:<40} {marker}")

    print(f"\n[3/3] 抓取完成，共 {len(all_annotations)} 个控件")

    # 保存 JSON
    OUT_JSON.write_text(json.dumps(all_annotations, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[OK] JSON: {OUT_JSON}")

    # 统计
    has_pos = sum(1 for i in all_annotations if i.get('position'))
    has_color = sum(1 for i in all_annotations if i.get('text_color'))
    has_font = sum(1 for i in all_annotations if i.get('font_family'))
    has_grad = sum(1 for i in all_annotations if i.get('gradient'))
    has_br = sum(1 for i in all_annotations if i.get('border_radius'))
    has_shadow = sum(1 for i in all_annotations if i.get('shadow'))
    is_valid = sum(1 for i in all_annotations if i.get('is_annotating'))

    print(f"\n=== 统计摘要 ===")
    print(f"  总控件数: {len(all_annotations)}")
    print(f"  有效标注: {is_valid}")
    print(f"  有位置: {has_pos}  有颜色: {has_color}  有字体: {has_font}")
    print(f"  有渐变: {has_grad}  有圆角: {has_br}  有阴影: {has_shadow}")

    # 保存 TXT
    lines = ["=== 蓝湖标注面板 — 全部控件遍历结果 ===\n"]
    for i, item in enumerate(all_annotations):
        lines.append(f"\n--- [{i+1}] {item.get('layer_name', '?')} ---")
        if item.get('position'):
            p = item['position']
            lines.append(f"  位置: x={p['x']}  y={p['y']}")
        if item.get('size'):
            s = item['size']
            lines.append(f"  大小: {s['width']} × {s['height']}")
        if item.get('font_family'):
            lines.append(f"  字体: {item['font_family']} {item.get('font_weight', '')}")
        if item.get('font_size'):
            lines.append(f"  字号: {item['font_size']}  行高: {item.get('line_height', '?')}  字间距: {item.get('letter_spacing', '?')}")
        if item.get('text_color'):
            lines.append(f"  颜色: {item['text_color']}  {item.get('text_color_rgba', '')}")
        if item.get('gradient') and isinstance(item['gradient'], dict):
            g = item['gradient']
            if g.get('type') == 'multi-stop':
                lines.append(f"  渐变: {len(g.get('stops',[]))}色多色渐变")
                for s in g['stops']:
                    lines.append(f"    - {s['color']} alpha:{s['alpha']}")
            elif g.get('type') == 'simple':
                lines.append(f"  渐变: {g.get('start')} → {g.get('end')}")
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

    OUT_TXT.write_text('\n'.join(lines), encoding='utf-8')
    print(f"[OK] TXT: {OUT_TXT}")


if __name__ == "__main__":
    main()