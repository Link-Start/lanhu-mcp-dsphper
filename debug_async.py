#!/usr/bin/env python3
"""调试：测试单个点击返回的原始内容。"""

import subprocess

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
    return result.stdout.decode('utf-8', errors='replace').strip()

# 测试1: 纯文本（已知有效）
js1 = r"""
(function(){
    var t = document.body ? document.body.innerText : '';
    var end = t.indexOf('历史版本');
    if (end === -1) end = t.length;
    return t.slice(0, 200);
})()
"""
print("=== 测试1: 纯文本 innerText ===")
r = run_js(js1)
print(f"长度: {len(r)} | 内容: {repr(r[:100])}")

# 测试2: async + await（可能不被 AppleScript 支持）
js2 = r"""
(async function(){
    return "hello async";
})()
"""
print("\n=== 测试2: async 函数 ===")
r = run_js(js2)
print(f"长度: {len(r)} | 内容: {repr(r[:100])}")

# 测试3: 点击后等待
js3 = r"""
(function(){
    var items = document.querySelectorAll('.layers_item');
    if (!items || items.length === 0) return JSON.stringify({error: 'no_items'});
    var item = items[1];
    item.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:100, clientY:100}));
    item.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    item.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    return JSON.stringify({idx: 1, total: items.length});
})()
"""
print("\n=== 测试3: 点击返回 JSON ===")
r = run_js(js3)
print(f"长度: {len(r)} | 内容: {repr(r[:200])}")

# 测试4: 带 setTimeout 但不用 async（同步写法）
js4 = r"""
(function(){
    var items = document.querySelectorAll('.layers_item');
    if (!items || items.length === 0) return JSON.stringify({error: 'no_items'});
    var item = items[1];
    item.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:100, clientY:100}));
    item.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
    item.dispatchEvent(new MouseEvent('click', {bubbles:true}));
    // 同步等待 300ms（阻塞）
    var start = Date.now();
    while (Date.now() - start < 300) {}
    var t = document.body ? document.body.innerText : '';
    var end = t.indexOf('历史版本');
    if (end === -1) end = t.length;
    return t.slice(0, 100);
})()
"""
print("\n=== 测试4: 同步阻塞式等待 ===")
r = run_js(js4)
print(f"长度: {len(r)} | 内容: {repr(r[:200])}")
