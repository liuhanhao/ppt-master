#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smartedu 链接 → 课件素材包，全自动抓取。

用法:
  python3 fetch_materials.py <smartedu链接> <输出目录> [--token XXX]

支持链接:
  同步课堂  basic.smartedu.cn/syncClassroom/classActivity?activityId=...
  备课课件  basic.smartedu.cn/...?resourceId=...
  精品课    basic.smartedu.cn/qualityCourse?courseId=...

产出（与 smartedu-source 工作流的输入约定一致）:
  <输出目录>/superboard/extracted/*.json   矢量内容源（含 document.json）
  <输出目录>/images/                       图片（含 ImageFill 背景图）
  <输出目录>/video/                        内嵌视频（若有）
  <输出目录>/audio/                        内嵌音频（若有）

要点:
  * 详情 JSON 与 superboard 本体【免登录】；图片/音视频需 token（401）。
  * 必须扫描【所有】图片来源：ImageShape 的 imageRes，以及
    paint.fill.astype=="ImageFill" 的 imageRes —— 只取前者会漏掉
    封面/尾页的大背景图，导致这些页渲染成空白。
"""

import glob
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile

UA = {'User-Agent': 'Mozilla/5.0'}
CDN = 'https://r1-ndr-private.ykt.cbern.com.cn'

DETAIL_API = [
    ('activityId', 'https://s-file-2.ykt.cbern.com.cn/zxx/ndrv2/national_lesson/resources/details/{}.json'),
    ('resourceId', 'https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/prepare_sub_type/resources/details/{}.json'),
    ('courseId',   'https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/{}.json'),
]


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def http_get(url, token=None):
    if token:
        url += ('&' if '?' in url else '?') + 'accessToken=' + token
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=300).read()


def parse_link(link):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    for key, tpl in DETAIL_API:
        if key in q and q[key][0]:
            return key, q[key][0], tpl.format(q[key][0])
    return None, None, None


def iter_shapes(node):
    """深度遍历所有 shape（含 Group 子形状）。"""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from iter_shapes(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_shapes(v)


def lesson_scope(detail, hour_id):
    """按 resource_structure 的课时分组，返回该课时的资源 id 集合。

    多课时链接里同一个 activity 挂着 N 套课件/教学设计，res_ref 形如
    "$.relations.national_course_resource[0,1,2,3,4]" 圈定本课时用到的下标。
    不过滤会取到最后一个课时的课件。返回 None 表示不限定。
    """
    if not hour_id:
        return None
    for les in ((detail.get('resource_structure') or {}).get('relations') or []):
        if les.get('id') != hour_id:
            continue
        ids = set()
        for ref in les.get('res_ref') or []:
            key = ref.split('[')[0].split('.')[-1]
            lst = (detail.get('relations') or {}).get(key) or []
            m = re.search(r'\[([\d,\s]+)\]', ref)
            if m:
                for i in (int(x) for x in m.group(1).split(',')):
                    if i < len(lst):
                        ids.add(lst[i].get('id'))
            else:
                ids.update(it.get('id') for it in lst if isinstance(it, dict))
        return ids or None
    return None


def find_courseware(detail, scope=None):
    """在详情 JSON 里找课件资源（coursewares）及其 superboard 地址。"""
    cands = []
    rel = detail.get('relations') or {}
    for k, v in rel.items():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    cands.append(item)
    for item in detail.get('ti_items') and [detail] or []:
        cands.append(item)

    best = None
    for c in cands:
        if c.get('resource_type_code') != 'coursewares':
            continue
        if scope is not None and c.get('id') not in scope:
            continue
        for ti in (c.get('ti_items') or []):
            flag = ti.get('ti_file_flag')
            stor = ti.get('ti_storages') or []
            if not stor:
                continue
            url = stor[0] if isinstance(stor[0], str) else (stor[0] or {}).get('relative_path') or (
                stor[0] or {}).get('url')
            if not url:
                continue
            if flag == 'superboard':
                best = (c, url, ti)
            elif flag == 'pdf' and best is None:
                best = (c, url, ti)
    return best


def collect_media(ex_dir):
    """
    扫描全部页面 JSON，收集媒体引用。
    返回 {kind: {file_name: uri_string}}，kind ∈ image/video/audio
    """
    out = {'image': {}, 'video': {}, 'audio': {}}

    def add(kind, res):
        if not isinstance(res, dict):
            return
        uri = res.get('uriString') or ''
        fn = res.get('fileName') or (uri.split('/')[-1] if uri else '')
        if fn and uri and fn not in out[kind]:
            out[kind][fn] = uri

    # 兜底：document.json 的 resourceTable 里还登记了视频封面等资源，
    # 它们不在任何 shape 的 imageRes 上，只扫页面会漏掉。
    docp = os.path.join(ex_dir, 'document.json')
    if os.path.exists(docp):
        try:
            d = json.load(open(docp, encoding='utf-8'))
            tbl = (d.get('resourceTable') or {}).get('tables')
            lst = tbl.get('value') if isinstance(tbl, dict) else (tbl or [])
            for item in lst or []:
                url = (item or {}).get('url') or ''
                low = url.lower()
                if '.png' in low or '.jpg' in low or '.jpeg' in low:
                    out['image'].setdefault(url.split('/')[-1], url)
                elif '.mp4' in low:
                    out['video'].setdefault(url.split('/')[-1], url)
                elif '.mp3' in low:
                    out['audio'].setdefault(url.split('/')[-1], url)
        except Exception:
            pass

    for fp in sorted(glob.glob(os.path.join(ex_dir, '*.json'))):
        try:
            data = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        for s in iter_shapes(data):
            # 1) 图片形状
            add('image', s.get('imageRes') or {})
            # 2) 【关键】图片填充（封面/尾页大背景图就在这里，极易漏掉）
            fill = (s.get('paint') or {}).get('fill') or {}
            if fill.get('astype') == 'ImageFill':
                add('image', fill.get('imageRes') or {})
            # 3) 音视频形状
            res = s.get('resource') or {}
            uri = str(res.get('uriString') or '')
            astype = str(s.get('astype') or '')
            if '.mp4' in uri.lower() or 'Video' in astype:
                add('video', res)
            elif '.mp3' in uri.lower() or 'Audio' in astype:
                add('audio', res)
    return out


def to_url(uri):
    """cs_path:${ref-path}/xxx → CDN 完整 URL"""
    if uri.startswith('cs_path:${ref-path}'):
        return CDN + uri.replace('cs_path:${ref-path}', '')
    if uri.startswith('http'):
        return uri
    return CDN + uri


def auto_token():
    """从浏览器 localStorage 的 LevelDB 里扫 token（尽力而为，失败返回 None）。"""
    roots = []
    for base in ('~/Library/Application Support/Google/Chrome',
                 '~/Library/Application Support/Microsoft Edge',
                 '~/Library/Application Support/com.apple.Safari'):
        p = os.path.expanduser(base)
        if os.path.isdir(p):
            roots.append(p)
    key = 'ND_UC_AUTH-e5649925-441d-4a53-b525-51a2f1c4e0a8&ncet-xedu&token'
    # 两种形态都出现过：JWT（eyJ...）与 112 位十六进制 access_token。
    pat = re.compile(rb'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}')
    pat_hex = re.compile(rb'[0-9A-Fa-f]{112}')
    # 注意必须也扫 .log：LevelDB 的近期写入常只在 log 里，只扫 *.ldb 会漏。
    for root in roots:
        for ext in ('*.ldb', '*.log'):
            for fp in glob.glob(os.path.join(root, '**', 'Local Storage', 'leveldb', ext), recursive=True):
                try:
                    raw = open(fp, 'rb').read()
                except Exception:
                    continue
                if key.encode() not in raw:
                    continue
                i = raw.find(b'access_token')
                if i < 0:
                    continue
                m = pat_hex.search(raw, i) or pat.search(raw)
                if m:
                    return m.group(0).decode()
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    link, out_dir = sys.argv[1], sys.argv[2]
    token = sys.argv[sys.argv.index('--token') + 1] if '--token' in sys.argv else None

    os.makedirs(out_dir, exist_ok=True)
    ex_dir = os.path.join(out_dir, 'superboard', 'extracted')

    kind, rid, api = parse_link(link)
    if not api:
        print('无法从链接解析出 activityId / resourceId / courseId')
        sys.exit(1)
    hour_id = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get('classHourId', [None])[0]
    print('链接类型: %s = %s%s' % (kind, rid, '  课时: ' + hour_id if hour_id else ''))

    print('拉取详情 JSON（免登录）...')
    detail = http_json(api)
    os.makedirs(os.path.join(out_dir, 'superboard'), exist_ok=True)
    json.dump(detail, open(os.path.join(out_dir, 'course.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    found = find_courseware(detail, lesson_scope(detail, hour_id))
    if not found:
        print('未找到课件（coursewares）资源')
        sys.exit(1)
    cw, sb_url, _ = found
    title = ((cw.get('global_title') or {}).get('zh-CN') or
             cw.get('title') or '课件')
    print('课件: %s' % title)

    # superboard 免登录
    print('下载 superboard（免登录）...')
    os.makedirs(ex_dir, exist_ok=True)
    blob = http_get(sb_url)
    zp = os.path.join(out_dir, 'superboard', 'doc.superboard.zip')
    open(zp, 'wb').write(blob)
    with zipfile.ZipFile(zp) as z:
        z.extractall(ex_dir)
    print('  解压 %d 个文件' % len(os.listdir(ex_dir)))

    media = collect_media(ex_dir)
    print('媒体引用: 图片%d 视频%d 音频%d' % (len(media['image']), len(media['video']), len(media['audio'])))

    if not token and (media['image'] or media['video'] or media['audio']):
        token = auto_token()
        if token:
            print('自动取到 token（长度 %d）' % len(token))
            open(os.path.join(out_dir, 'token.txt'), 'w').write(token)
    if not token:
        print('\n!! 未取到 token，图片/音视频将下载失败。')
        print('   解决：浏览器登录 smartedu 后重跑，或用 --token XXX 传入。')

    subdir = {'image': 'images', 'video': 'video', 'audio': 'audio'}
    report = {}
    for kind_m, items in media.items():
        d = os.path.join(out_dir, subdir[kind_m])
        if not items:
            continue
        os.makedirs(d, exist_ok=True)
        ok = 0
        for fn, uri in items.items():
            dst = os.path.join(d, fn)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                ok += 1
                continue
            try:
                data = http_get(to_url(uri), token)
                open(dst, 'wb').write(data)
                ok += 1
            except Exception as e:
                print('  ✗ %s: %s' % (fn[:40], str(e)[:60]))
        report[kind_m] = (ok, len(items))
        print('  %-6s %d/%d' % (subdir[kind_m], ok, len(items)))

    print('\n完成: %s' % out_dir)
    return report


if __name__ == '__main__':
    main()
