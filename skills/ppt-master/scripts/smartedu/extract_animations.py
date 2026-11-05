#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 superboard 提取每页动画，输出可读的动画参考（animations_ref.md）。

用法:
  python3 extract_animations.py <素材目录>

产出:
  <素材目录>/animations_ref.md

用途:
  smartedu-source 工作流把它交给 Generate 作为「动画参考」：
  - Default 路由：Strategist 读它，把每页动画意图写进 design_spec.md §IX 的
    Motion suggestion。
  - Quick 路由：主 agent 直接读，在 motion gate 判断是否给元素加动画。
  它不是 animations.json，不参与导出；真正的对象动画由 customize-animations
  阶段按新页面的顶层 group 落地。

要点:
  * 动画挂在 shape 上，锚点是 superboard spid，不是新页面的 SVG group——
    所以只能提供「语义参考」，不能按 spid 直接映射到重构后的元素。
  * 页面顺序以 document.json 的 pages.value 为准，Page N 与 source.md 的
    <!-- Page N --> 对齐。
  * 效果/触发只做常见值的中文注记，未收录的原样输出，由模型自行判断。
"""

import json
import os
import re
import sys

EFFECT_ZH = {
    'In_Fade': '进入·淡入',
    'In_Fly': '进入·飞入',
    'In_Wipe': '进入·擦除',
    'In_Zoom': '进入·缩放',
    'Sample': '样例/未知',
}

TIMING_ZH = {
    'AtClick': '点击时',
    'WithLast': '与上一项同时',
    'AtLastFinish': '上一项之后',
}


def page_order(ex_dir):
    """按 document.json 的 pages.value 返回页文件名顺序。"""
    dp = os.path.join(ex_dir, 'document.json')
    if not os.path.exists(dp):
        return []
    try:
        d = json.load(open(dp, encoding='utf-8'))
    except Exception:
        return []
    return ((d.get('pages') or {}).get('value') or [])


def shape_text(shape):
    """取该 shape 内的文字，用于标识「哪个元素在动」。"""
    parts = []

    def walk(node):
        if isinstance(node, dict):
            tdl = node.get('textDataList')
            if isinstance(tdl, dict):
                for run in tdl.get('value') or []:
                    if isinstance(run, dict) and isinstance(run.get('insert'), str):
                        parts.append(run['insert'])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(shape)
    # 转码器会把内部标记写进正文（如 superboard_first_line_indent），清掉
    text = re.sub(r'superboard_\w+', '', ''.join(parts))
    return text.strip().replace('\n', ' ')


def collect_page_anims(page):
    """返回该页的动画条目列表（按 order 排序）。"""
    rows = []

    def walk(node):
        if isinstance(node, dict):
            al = node.get('animationList') or {}
            vals = (al.get('value') if isinstance(al, dict) else al) or []
            for a in vals:
                if not isinstance(a, dict):
                    continue
                rows.append({
                    'order': a.get('order'),
                    'effect': (a.get('name') or {}).get('name') or '',
                    'timing': (a.get('playTiming') or {}).get('name') or '',
                    'duration': a.get('durationMS'),
                    'delay': a.get('delayMS'),
                    'trigger_shape': a.get('triggerShapeId'),
                    'text': shape_text(node),
                })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(page)
    rows.sort(key=lambda r: (r['order'] is None, r['order']))
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 1
    mat_dir = argv[0]
    ex_dir = os.path.join(mat_dir, 'superboard', 'extracted')
    if not os.path.isdir(ex_dir):
        print('找不到 %s —— 先跑 fetch_materials.py' % ex_dir)
        return 1

    order = page_order(ex_dir)
    if not order:
        print('document.json 缺 pages.value，无法确定页序')
        return 1

    out = ['# 动画参考（来自 superboard）', '',
           '> 这是**语义参考**，不是要照搬的动画。锚点是 superboard 的 shape，',
           '> 与重构后的页面 group 不对应；只用来判断「哪一页、哪些元素、按什么',
           '> 节奏出现」，落地时按新页面的顶层 group 重新设计。', '',
           '| Page | 步 | 元素文字 | 效果 | 触发 | 时长 | 备注 |',
           '|---|---|---|---|---|---|---|']

    total_pages = 0
    total_anims = 0
    animated_pages = 0
    for idx, fname in enumerate(order, 1):
        fp = os.path.join(ex_dir, fname)
        if not os.path.exists(fp):
            continue
        total_pages += 1
        try:
            page = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        rows = collect_page_anims(page)
        if not rows:
            continue
        animated_pages += 1
        total_anims += len(rows)
        for r in rows:
            effect = EFFECT_ZH.get(r['effect'], r['effect'])
            timing = TIMING_ZH.get(r['timing'], r['timing'])
            note = []
            if r['trigger_shape']:
                note.append('点形状触发')
            if r['delay']:
                note.append('延迟 %sms' % r['delay'])
            text = (r['text'] or '（无文字）')[:36]
            out.append('| %d | %s | %s | %s | %s | %sms | %s |' % (
                idx, r['order'], text,
                effect, timing, r['duration'], '；'.join(note)))

    out += ['', '## 汇总', '',
            '- 页数：%d，其中有动画页：%d' % (total_pages, animated_pages),
            '- 动画条目：%d' % total_anims,
            '- 用法：Default 写进 `design_spec.md §IX` 的 `Motion suggestion`；'
            'Quick 在 motion gate 直接判断。']

    dst = os.path.join(mat_dir, 'animations_ref.md')
    open(dst, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print('已写出 %s（%d 页有动画，共 %d 条）' % (dst, animated_pages, total_anims))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
