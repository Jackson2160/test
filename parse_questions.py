# -*- coding: utf-8 -*-
"""解析四份安全生产题库 Markdown，生成 quiz_data*.py 数据文件。

格式约定（源自 PDF 转 MD）：
- 一级/二级标题划分章与题型小节（单项选择/多项选择/判断/简答）
- 选择题：题干块 + 选项区（A、B、C 前缀可能缺失、多选项可能同行）+ "答案：X" 行
- 判断题：题干整块，句尾（√）/（×）标记，可能多题粘连成一块
- 简答：逐"块"状态机：题干块 → 独立"答案："块 → 答案若干块；
  PDF 折行可能把题干尾行粘在上一答案块的最后一行
"""
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"d:\安全生产题库"

FILES = [
    {"src": "2025安全生产标准化题库（一线人员）.md", "out": "quiz_data.py",
     "var": "QUESTIONS_PART1", "start_chapter": 1, "label": "一线人员"},
    {"src": "2025安全生产标准化题库（中层干部、管理人员）.md", "out": "quiz_data2.py",
     "var": "QUESTIONS_PART2", "start_chapter": 2, "label": "中层干部、管理人员"},
    {"src": "2025安全生产标准化题库（单位负责人）.md", "out": "quiz_data3.py",
     "var": "QUESTIONS_PART3", "start_chapter": 3, "label": "单位负责人"},
    {"src": "安全生产标准化考试题库-（专项标准）.md", "out": "quiz_data4.py",
     "var": "QUESTIONS_PART4", "start_chapter": None, "label": "专项标准"},
]

SUB_CHAPTERS = {"洁净厂房": 4, "电子装配作业": 5, "危险化学品": 6, "辐射作业": 7}

OPT_HEAD = re.compile(r"^([A-H])\s*[、.．]\s*")
INLINE_SPLIT = re.compile(r"(?:^|\s)([A-H])\s*[、.．]\s*")
ANSWER_LINE = re.compile(r"^答\s*案\s*[:：](.*)$")
ANSWER_ONLY = re.compile(r"^答\s*案\s*[:：]\s*$")
STEM_HINT = re.compile(r"（\s*）|（\s+）")
STEM_KEYWORDS = ("请", "简述", "简答", "说明", "写出", "列举", "回答", "如何",
                 "怎样", "哪些", "什么", "为什么", "指")
JUDGE_MARK = re.compile(r"[（(]\s*([√×])\s*[)）]")
NUM_HEAD = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+\s*[、.．)）]|\（\d+\）)")
TERMINAL = "。；？!?："
SECT_MAP = {"单项选择": "single", "多项选择": "multi", "判断": "judge", "简答": "blank"}
DIFFICULTY = {"single": 1, "judge": 1, "multi": 2, "blank": 2}

warnings = []
all_parsed = {}
_short_pending = {}


def clean(s):
    s = s.replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def ends_terminal(s):
    s = s.rstrip()
    return bool(s) and s[-1] in TERMINAL


def looks_like_short_stem(s):
    return bool(s) and s[-1] in "？?。" and not NUM_HEAD.match(s)


def merge_wrapped(blocks):
    """拼接被 PDF 换行截断的段落（上一块不以标点结尾且下一块非编号/选项/答案开头）。"""
    out = []
    for b in blocks:
        if (out and not ends_terminal(out[-1]) and not NUM_HEAD.match(b)
                and not OPT_HEAD.match(b) and not ANSWER_LINE.match(b)
                and not INLINE_SPLIT.match(" " + b)):
            out[-1] = out[-1].rstrip("- ") + b
        else:
            out.append(b)
    return out


def mark_count(l):
    """行首起连续的选项字母标记数（要求 A 起始、连续）；不足 2 返回 0。"""
    ms = marks_of(l)
    if len(ms) < 2 or ms[0].start() != 0:
        return 0
    letters = [m.group(1) for m in ms]
    if letters[0] != "A":
        return 0
    return len(letters) if all(ord(b) - ord(a) == 1
                               for a, b in zip(letters, letters[1:])) else 0


def marks_of(l):
    """行内合法的选项标记（字母前为行首或空白，后接 '、'/'.'/ '．'）。"""
    return [m for m in INLINE_SPLIT.finditer(l)
            if m.start() == 0 or l[m.start() - 1].isspace()]


def section_of(title):
    for key, val in SECT_MAP.items():
        if key in title:
            return val
    return None


def parse_file(cfg):
    path = BASE + "\\" + cfg["src"]
    with open(path, encoding="utf-8") as f:
        raw = f.read().splitlines()

    questions = []
    decls = []
    chapter = cfg["start_chapter"]
    sect = None
    buf, cur_block = [], []
    started = False

    def flush_block():
        nonlocal cur_block
        if cur_block:
            buf.append("\n".join(cur_block))
            cur_block = []

    def run_handler(blocks):
        if not blocks or sect is None:
            return
        if sect in ("single", "multi"):
            process_choice(blocks, sect, cfg, chapter, questions)
        elif sect == "judge":
            process_judge(blocks, cfg, chapter, questions)

    def finish_group():
        nonlocal buf
        flush_block()
        if sect == "blank":
            process_short(buf, cfg, chapter, questions)
        elif buf:
            run_handler(buf)
        buf = []

    for ln, line in enumerate(raw, 1):
        s = line.strip()
        if s.startswith("#"):
            flush_block()
            title = s.lstrip("#").strip()
            st = section_of(title)
            if st:
                if sect != st:
                    finish_group()
                    sect = st
                    m = re.search(r"共\s*(\d+)\s*题", title)
                    if m:
                        decls.append((st, chapter, int(m.group(1)), ln))
            elif cfg["start_chapter"] is None and title in SUB_CHAPTERS:
                finish_group()
                sect = None
                chapter = SUB_CHAPTERS[title]
            elif sect == "blank":
                cur_block.append(title)      # 题干误标为标题
            else:
                finish_group()
                sect = None
            started = True
            continue
        if not s:
            flush_block()
            continue
        if not started:
            continue
        cur_block.append(s)
        if sect in ("single", "multi", "judge") and ANSWER_LINE.match(s):
            flush_block()
            run_handler(buf)
            buf = []
    finish_group()
    return questions, decls


def process_judge(blocks, cfg, chapter, questions):
    text = "\n".join(blocks)
    marks = list(JUDGE_MARK.finditer(text))
    if not marks:
        warnings.append(f"[{cfg['src']}] 判断题组缺√/×: {text[:30]}")
        return
    prev_end = 0
    for m in marks:
        stem = clean(text[prev_end:m.start()])
        prev_end = m.end()
        if not stem:
            continue
        questions.append({"chapter": chapter, "source": cfg["label"], "type": "judge",
                          "difficulty": 1, "q": stem,
                          "answer": m.group(1) == "√", "explain": ""})
    tail = clean(text[prev_end:])
    if tail:
        warnings.append(f"[{cfg['src']}] 判断题组尾部残留: {tail[:30]}")


def process_choice(blocks, sect, cfg, chapter, questions):
    # blocks 恰好一道题：题干块+选项块 + 以"答案：..."结尾的块
    am = ANSWER_LINE.match(blocks[-1].split("\n")[-1].strip())
    if not am:
        warnings.append(f"[{cfg['src']}] 答案缺失: {blocks[0][:26]}")
        return
    ans_raw = am.group(1).strip()
    letters = "".join(sorted(set(re.sub(r"[^A-H]", "",
                                         unicodedata.normalize("NFKC", ans_raw.upper())))))
    # 展平为 (是否块首行, 行文本)
    lines = []
    for b in blocks[:-1]:
        first = True
        for x in b.split("\n"):
            if not x.strip():
                continue
            lines.append(("B" if first else "", x.strip()))
            first = False
    while lines and lines[-1][0] == "":
        lines.pop()
    if not lines:
        warnings.append(f"[{cfg['src']}] 题目块为空: {blocks[0][:26]}")
        return

    first_line = lines[0][1]
    # 选项区起点：第一处（非首行）带合法选项标记的行；题干可能折行占多个块
    oi = None
    for k in range(1, len(lines)):
        if marks_of(lines[k][1]):
            oi = k
            break
    if oi is None:
        # 首行即标记行（题干与选项同块且选项在前）
        oi = 1 if marks_of(lines[0][1]) else len(lines)

    raw_opts = [l for _, l in lines[oi:]]
    stem_extra = ""
    if oi < len(lines) and any(marks_of(l) for l in raw_opts):
        pieces = []
        expect = "A"
        buf = []            # 等待归属的无标记行
        for l in raw_opts:
            ms = marks_of(l)
            if not ms:
                buf.append(l)
                continue
            # 行首残留文本（首个标记之前）
            head = l[:ms[0].start()].strip()
            if pieces and head:
                pieces[-1] = (pieces[-1][0], pieces[-1][1] + head)
            elif head:
                # 题干粘在选项区首行：残句含空括号 → 归题干，否则当选项 A
                if STEM_HINT.search(head) or (head.endswith("。") and "（" in head):
                    stem_extra = head
                else:
                    pieces.append(("A", head))
                    expect = "B"
            if buf:
                if pieces and ms[0].start() > 0:
                    # buf 及行首残留属于上一项的折行延续
                    pieces[-1] = (pieces[-1][0],
                                  pieces[-1][1] + "".join(buf) + l[:ms[0].start()])
                elif pieces:
                    # buf 是缺失字母的选项文本（字母标记丢失）
                    for x in buf:
                        pieces.append((expect, x))
                        expect = chr(ord(expect) + 1)
                buf = []
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(l)
                pieces.append((m.group(1), l[m.end():end].strip()))
            expect = chr(ord(ms[-1].group(1)) + 1)
        # 尾部无标记行：若答案字母超出已解析项且行数恰好补上缺口 → 它们是被丢字母的选项
        if buf:
            have = [a for a, _ in pieces]
            gap = (ord(max(letters)) - ord(have[-1])) if (letters and have) else 0
            if gap == len(buf) and max(letters) > have[-1]:
                for x in buf:
                    pieces.append((expect, x))
                    expect = chr(ord(expect) + 1)
            else:
                pieces[-1] = (pieces[-1][0], pieces[-1][1] + "".join(buf))
        seq = [a for a, _ in pieces]
        if not seq or seq[0] != "A":
            warnings.append(f"[{cfg['src']}] 选项序列异常{seq}: {first_line[:24]}")
            return
        if any(ord(b) - ord(a) != 1 for a, b in zip(seq, seq[1:])):
            # 字母重复/跳字：按出现顺序重编号（保留选项文本）
            warnings.append(f"[{cfg['src']}] 选项字母不连续{seq}: {first_line[:24]}")
            return
        opts = pieces
        stem_end = oi
    else:
        # 无前缀：反向找含空括号'（ ）'的题干行；找不到则题干=第一块
        k = len(lines) - 1
        stem_k = None
        while k > 0:
            if STEM_HINT.search(lines[k][1]):
                stem_k = k
                break
            k -= 1
        if stem_k is not None:
            opts = [("", l) for _, l in lines[stem_k + 1:]]
            stem_end = stem_k + 1
            while stem_end - 1 >= 1 and lines[stem_end - 1][0] == "":
                stem_end -= 1
        else:
            stem_end = 1
            while stem_end < len(lines) and lines[stem_end][0] != "B":
                stem_end += 1
            opts = [("", l) for _, l in lines[stem_end:]]
        if len(opts) < 2:
            warnings.append(f"[{cfg['src']}] 无前缀选项不足: {first_line[:26]}")
            return
    stem = clean("".join(l for _, l in lines[:stem_end]) + stem_extra)

    if all(a for a, _ in opts):
        lmap = {a: k for k, (a, _) in enumerate(opts)}
        bad = [c for c in letters if c not in lmap]
        idxs = [lmap[c] for c in letters if c in lmap]
        if bad:
            warnings.append(f"[{cfg['src']}] 答案字母{bad}超出{len(opts)}选项: {stem[:26]}")
            return
    else:
        idxs = [ord(c) - 65 for c in letters]
        if any(not 0 <= x < len(opts) for x in idxs):
            warnings.append(f"[{cfg['src']}] 无前缀答案越界{ans_raw}: {stem[:26]}")
            return
    options = [t for _, t in opts]
    if sect == "single":
        if len(idxs) != 1:
            warnings.append(f"[{cfg['src']}] 单选答案数={len(idxs)} 答案{ans_raw}: {stem[:26]}")
        if not idxs:
            return
        answer = idxs[0]
    else:
        if len(idxs) < 2:
            warnings.append(f"[{cfg['src']}] 多选答案仅1个 答案{ans_raw}: {stem[:26]}")
        answer = sorted(idxs)
    questions.append({"chapter": chapter, "source": cfg["label"], "type": sect,
                      "difficulty": DIFFICULTY[sect], "q": stem,
                      "options": options, "answer": answer, "explain": ""})


def emit_short(stem_lines, part_list, cfg, chapter, questions):
    stem_txt = clean("".join(stem_lines))
    ans = clean("\n".join(merge_wrapped([p for p in part_list if p])))
    if not stem_txt:
        warnings.append(f"[{cfg['src']}] 简答题干为空: {ans[:24]}")
        return
    if not ans:
        warnings.append(f"[{cfg['src']}] 简答题无答案，跳过: {stem_txt[:30]}")
        return
    # 简答归一化为 blank：参考答案存入 answer 列表，app 层做自评展示
    questions.append({"chapter": chapter, "source": cfg["label"], "type": "blank",
                      "difficulty": 2, "q": stem_txt,
                      "answer": [ans], "explain": ans})


def is_stem_end(s):
    """简答题干尾行特征：以问号结尾，或以。结尾且含提问关键词的短句。"""
    if not s:
        return False
    if s.endswith(("？", "?")):
        return True
    return (s.endswith("。") and len(s) <= 60
            and any(k in s for k in STEM_KEYWORDS))


def process_short(blocks, cfg, chapter, questions):
    """整节两遍处理：以独立 '答案：' 行为锚点，
    结构 [题干N][答案：][答案N正文][题干N+1][答案：]…
    正确答案正文紧跟其自身标记之后、下一题干之前。"""
    lines = []
    for b in blocks:
        for x in b.split("\n"):
            if x.strip():
                lines.append(x.strip())

    def is_marker(s):
        am = ANSWER_LINE.match(s)
        return bool(am) and not am.group(1).strip()

    markers = [i for i, l in enumerate(lines) if is_marker(l)]
    if not markers:
        if any(l for l in lines):
            warnings.append(f"[{cfg['src']}] 简答节缺'答案：'标记: {lines[0][:26]}")
        return

    # 第一遍：定位每题题干起点（紧邻其标记之前，向前吞掉折行的非终止行）
    stem_start = []
    for idx, mi in enumerate(markers):
        lo = markers[idx - 1] + 1 if idx > 0 else 0
        si = mi - 1
        if si >= lo and is_stem_end(lines[si]):
            while si - 1 >= lo and not ends_terminal(lines[si - 1]) \
                    and not is_marker(lines[si - 1]):
                si -= 1
        elif si >= lo:
            si = mi - 1  # 题干尾行无问号：仅取标记前一行
        stem_start.append(si)

    # 第二遍：题干=stem_start[i]..marker，答案=marker+1..下一题干起点
    preamble = lines[0:stem_start[0]]
    if preamble:
        warnings.append(f"[{cfg['src']}] 简答节前导残留: {preamble[0][:26]}")
    for idx, mi in enumerate(markers):
        stem = lines[stem_start[idx]:mi]
        ans_lo = mi + 1
        ans_hi = stem_start[idx + 1] if idx + 1 < len(markers) else len(lines)
        ans = lines[ans_lo:ans_hi]
        emit_short(stem, ans, cfg, chapter, questions)


def write_module(cfg, questions):
    lines = [
        "# -*- coding: utf-8 -*-",
        f"# 「{cfg['label']}」安全生产标准化题库数据（共 {len(questions)} 题）。",
        "",
        f"{cfg['var']} = [",
    ]
    last_ch = None
    for q in questions:
        if q["chapter"] != last_ch:
            lines.append(f'    # ===== 第 {q["chapter"]} 章 {q["source"]} =====')
            last_ch = q["chapter"]
        keys = ["chapter", "type", "difficulty", "q", "options", "answer", "explain"]
        parts = [f'"{k}": {q[k]!r}' for k in keys if k in q]
        lines.append("    {" + ", ".join(parts) + "},")
    lines.append("]")
    lines.append("")
    with open(BASE + "\\" + cfg["out"], "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    for cfg in FILES:
        _short_pending.clear()
        qs, decls = parse_file(cfg)
        all_parsed[cfg["src"]] = (qs, decls)
        counts = {}
        for q in qs:
            counts[q["type"]] = counts.get(q["type"], 0) + 1
        print(f"{cfg['src']}: {len(qs)} 题 {counts}")

    print("\n=== 声明题量核对 ===")
    mismatch = 0
    for src, (qs, decls) in all_parsed.items():
        for st, ch, n, ln in decls:
            got = sum(1 for q in qs if q["type"] == st and q["chapter"] == ch)
            flag = "OK " if got == n else "MISMATCH"
            if got != n:
                mismatch += 1
            print(f"{flag} {src} 第{ch}章 {st} 声明{n} 实际{got} (标题行{ln})")

    print(f"\n警告 {len(warnings)} 条:")
    for w in warnings[:80]:
        print("  WARN", w)
    if len(warnings) > 80:
        print(f"  ...省略 {len(warnings) - 80} 条")
    total = sum(len(v[0]) for v in all_parsed.values())
    print(f"\n总题量: {total}  题量不符小节数: {mismatch}")
    for cfg in FILES:
        write_module(cfg, all_parsed[cfg["src"]][0])
    print("已写出:", ", ".join(c["out"] for c in FILES))


if __name__ == "__main__":
    import io
    buf = io.StringIO()
    _real_stdout, sys.stdout = sys.stdout, buf
    try:
        main()
    finally:
        sys.stdout = _real_stdout
    report = buf.getvalue()
    with open(BASE + "\\_parse_report.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print("报告已写入 _parse_report.txt")
