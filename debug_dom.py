#!/usr/bin/env python3
"""探测蓝湖 detailDetach 页面的 DOM 结构，找出图层相关元素。"""

import subprocess
import sys

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
        print(f"[Error] osascript: {result.stderr.decode()}")
        return "ERROR"
    return result.stdout.decode('utf-8', errors='replace').strip()

print("=== 探测 DOM 结构 ===\n")

# 1. 找所有包含 "layer" 的 class
js1 = r"""
(function(){
    var classes = new Set();
    document.querySelectorAll('*').forEach(function(el){
        var c = el.className || '';
        if (typeof c === 'string' && c.indexOf('layer') !== -1) {
            classes.add(c);
        }
    });
    return Array.from(classes).slice(0, 50).join('\n');
})()
"""
print("--- 包含 'layer' 的 class ---")
r = run_js(js1)
print(r[:2000] or '(无)')

# 2. 找所有包含 "layers" 的 class
js2 = r"""
(function(){
    var classes = new Set();
    document.querySelectorAll('*').forEach(function(el){
        var c = el.className || '';
        if (typeof c === 'string' && c.indexOf('layers') !== -1) {
            classes.add(c);
        }
    });
    return Array.from(classes).slice(0, 50).join('\n');
})()
"""
print("\n--- 包含 'layers' 的 class ---")
r = run_js(js2)
print(r[:2000] or '(无)')

# 3. 找所有 __vue__ 实例
js3 = r"""
(function(){
    var vueEls = Array.from(document.querySelectorAll('*')).filter(function(el){ return !!el.__vue__; });
    var info = vueEls.slice(0, 20).map(function(el){
        return {
            tag: el.tagName,
            class: (el.className||'').slice(0,60),
            hasGDetail: !!(el.__vue__ && el.__vue__.g_detail),
            gDetailKeys: el.__vue__ && el.__vue__.g_detail ? Object.keys(el.__vue__.g_detail).slice(0,10) : []
        };
    });
    return JSON.stringify(info);
})()
"""
print("\n--- 有 __vue__ 的元素 ---")
r = run_js(js3)
print(r[:3000] or '(无)')

# 4. 检查 g_detail 里的 layers
js4 = r"""
(function(){
    var vueEls = Array.from(document.querySelectorAll('*')).filter(function(el){ return !!el.__vue__ && el.__vue__.g_detail && el.__vue__.g_detail.layers; });
    if (vueEls.length === 0) return "NOT_FOUND";
    var vm = vueEls[0].__vue__;
    var layers = vm.g_detail.layers;
    return JSON.stringify({
        totalLayers: layers.length,
        first5: layers.slice(0,5).map(function(L){ return {name: L.name, type: L.type, visible: L.visible, width: L.width, height: L.height}; })
    });
})()
"""
print("\n--- g_detail.layers ---")
r = run_js(js4)
print(r[:2000] or '(无)')

# 5. 检查 body innerText 前500字符
js5 = r"""
(function(){
    return (document.body ? document.body.innerText : '').slice(0, 500);
})()
"""
print("\n--- body innerText 前500字符 ---")
r = run_js(js5)
print(r)

# 6. 找所有按钮文本
js6 = r"""
(function(){
    var btns = [];
    document.querySelectorAll('button, [role="button"], .mu-btn, .btn').forEach(function(el){
        var t = (el.textContent||'').trim();
        if (t) btns.push(t.slice(0,30));
    });
    return btns.slice(0,30).join('\n');
})()
"""
print("\n--- 按钮文本 ---")
r = run_js(js6)
print(r[:1000] or '(无)')

# 7. 找 CSS 选中的元素数
js7 = r"""
(function(){
    var counts = {
        '.layers_item': document.querySelectorAll('.layers_item').length,
        '.layer_item': document.querySelectorAll('.layer_item').length,
        '.layers': document.querySelectorAll('.layers').length,
        '.layer': document.querySelectorAll('.layer').length,
        'all_divs': document.querySelectorAll('div').length,
        'all_spans': document.querySelectorAll('span').length,
    };
    return JSON.stringify(counts);
})()
"""
print("\n--- 元素数量统计 ---")
r = run_js(js7)
print(r)
