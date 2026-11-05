#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载配套 PDF（教学设计 / 学习任务单 / 作业练习）+ 课件 PDF（source.pdf）。

用法:
  python3 fetch_pdfs.py <素材目录> <输出文件名前缀> [--token XXX] [--lesson lesson_1]

素材目录是 fetch_materials.py 的产出（内含 course.json）。token 依次从
--token、<素材目录>/token.txt、浏览器 LevelDB 取。

产出:
  <前缀>-教学设计.pdf  <前缀>-学习任务单.pdf  <前缀>-作业练习.pdf
  <素材目录>/source.pdf   课件 PDF 转码件（供 source_to_md.py 提取正文）

要点:
  * 平台不提供 docx/pptx 原文件，即使标题写 .docx/.pptx 也只有 PDF 转码件。
  * 授课视频是 m3u8 加密流，不在范围内，跳过。
  * 课件 PDF 与 superboard 内容同源；在 smartedu-source 工作流里它是
    ppt-master 重构的唯一正文来源，所以固定落为 source.pdf。
"""

import json
import os
import sys

import fetch_materials as F

# 配套的三种文档资源；coursewares 单独落为 source.pdf，不进 LABEL
LABEL = {
    'lesson_plandesign': '教学设计',
    'learning_task': '学习任务单',
    'after_class_exercise': '作业练习',
}


def iter_resources(node):
    """递归找出所有带 resource_type_code 的资源项。

    精品课把资源放在 relations.course_resource[]，其它链接类型结构不同，
    递归比按固定路径取更稳。
    """
    if isinstance(node, dict):
        if 'resource_type_code' in node:
            yield node
        for v in node.values():
            yield from iter_resources(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_resources(v)


def pdf_url(res):
    """取该资源的 PDF 转码件地址（ti_storages 首个可用节点）。"""
    for ti in res.get('ti_items') or []:
        if ti.get('ti_file_flag') != 'pdf':
            continue
        for st in ti.get('ti_storages') or []:
            url = st if isinstance(st, str) else (st.get('relative_path')
                                                  or st.get('url'))
            if url:
                return url
    return None


def download(url, token, fp):
    """下载并校验一个 PDF，返回字节数；失败返回 None。"""
    try:
        data = F.http_get(url, token)
    except Exception as e:
        print('  x %s：%s' % (os.path.basename(fp), str(e)[:60]))
        return None
    if len(data) <= 1024:
        print('  x %s：内容过小(%d 字节)，token 可能已过期'
              % (os.path.basename(fp), len(data)))
        return None
    open(fp, 'wb').write(data)
    print('  ok %s (%d 字节)' % (fp, len(data)))
    return len(data)


def main():
    drop = {'--token', '--lesson'}
    args, i = [], 0
    while i < len(sys.argv[1:]):
        a = sys.argv[1:][i]
        if a in drop:
            i += 2
            continue
        args.append(a)
        i += 1
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    mat_dir, prefix = args[0], args[1]
    token = sys.argv[sys.argv.index('--token') + 1] if '--token' in sys.argv else None
    lesson = sys.argv[sys.argv.index('--lesson') + 1] if '--lesson' in sys.argv else None

    detail = json.load(open(os.path.join(mat_dir, 'course.json'), encoding='utf-8'))
    # 多课时链接会把两个课时的配套文档都递归出来，后下的覆盖先下的
    scope = F.lesson_scope(detail, lesson)

    if not token:
        tp = os.path.join(mat_dir, 'token.txt')
        if os.path.exists(tp):
            token = open(tp).read().strip()
    if not token:
        token = F.auto_token()
    if not token:
        print('!! 未取到 token，PDF 会下载失败。'
              '浏览器登录 smartedu 后重跑，或用 --token XXX 传入。')

    got = 0
    seen = set()
    source_done = False
    for res in iter_resources(detail):
        code = res.get('resource_type_code')
        # 同一资源会在 relations 的多个分组里重复出现
        rid = (code, res.get('id') or (res.get('global_title') or {}).get('zh-CN'))
        if scope is not None and res.get('id') not in scope:
            continue

        # 课件 PDF 固定落为 source.pdf（ppt-master 重构的正文来源）
        if code == 'coursewares' and not source_done:
            if rid in seen:
                continue
            seen.add(rid)
            url = pdf_url(res)
            if url and download(url, token, os.path.join(mat_dir, 'source.pdf')):
                got += 1
                source_done = True
            continue

        if code not in LABEL or rid in seen:
            continue
        seen.add(rid)
        url = pdf_url(res)
        if not url:
            print('  - %s：无 PDF 转码件' % LABEL[code])
            continue
        if download(url, token, '%s-%s.pdf' % (prefix, LABEL[code])):
            got += 1

    print('\n完成：下载 %d 个 PDF（含 source.pdf）' % got)


if __name__ == '__main__':
    main()
