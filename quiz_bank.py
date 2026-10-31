# -*- coding: utf-8 -*-
"""quiz_bank —— 题库聚合与查询层（纯内存，无磁盘 IO）。

职责：合并四个数据文件 → 分配稳定 ID → 按 ID 播种打乱选项 →
逐题型判题 → 把答案渲染为可读文本。app.py 只能经由本模块访问题目。
"""
from __future__ import annotations

import random
import string
from collections import defaultdict
from typing import Dict, List, Optional

from quiz_data import QUESTIONS_PART1
from quiz_data2 import QUESTIONS_PART2
from quiz_data3 import QUESTIONS_PART3
from quiz_data4 import QUESTIONS_PART4

TYPE_NAMES = {"single": "单选题", "multi": "多选题", "judge": "判断题",
              "blank": "简答题", "code": "代码题"}
DIFFICULTY_NAMES = {1: "★ 简单", 2: "★★ 中等", 3: "★★★ 困难"}

# 章号 → 章节标签（专项标准下含 4 个子专项）
CHAPTER_LABELS = {
    1: "一线人员", 2: "中层干部、管理人员", 3: "单位负责人",
    4: "专项·洁净厂房", 5: "专项·电子装配作业",
    6: "专项·危险化学品", 7: "专项·辐射作业",
}


def _label(q: dict) -> str:
    return CHAPTER_LABELS.get(q["chapter"], f"第{q['chapter']}章")


def _shuffle_options(q: dict) -> dict:
    """用 random.Random(id) 播种打乱选项，并同步重映射 answer 下标。
    保证同一题每次呈现顺序一致，且正确答案均匀分布。无选项题原样返回。"""
    opts = q.get("options")
    if not opts or len(opts) < 2:
        return q
    rng = random.Random(q["id"])
    order = list(range(len(opts)))
    rng.shuffle(order)                       # order[新位置] = 原下标
    old_to_new = {old: new for new, old in enumerate(order)}
    q["options"] = [opts[i] for i in order]
    t, a = q["type"], q["answer"]
    if t in ("single", "code"):
        q["answer"] = old_to_new[a]
    elif t == "multi":
        q["answer"] = sorted(old_to_new[x] for x in a)
    return q


def _build_bank() -> List[dict]:
    raw = list(QUESTIONS_PART1) + list(QUESTIONS_PART2) + \
        list(QUESTIONS_PART3) + list(QUESTIONS_PART4)
    per_chapter: Dict[int, int] = defaultdict(int)
    bank: List[dict] = []
    for q in raw:
        q = dict(q)                                   # 拷贝，避免污染源数据
        ch = q["chapter"]
        per_chapter[ch] += 1
        q["id"] = f"c{ch}_q{per_chapter[ch]:02d}"
        q["label"] = _label(q)
        bank.append(_shuffle_options(q))
    return bank


QUESTIONS = _build_bank()
_BY_ID: Dict[str, dict] = {q["id"]: q for q in QUESTIONS}
_BY_CHAPTER: Dict[int, List[dict]] = defaultdict(list)
for _q in QUESTIONS:
    _BY_CHAPTER[_q["chapter"]].append(_q)


# ---------- 对外接口 ----------
def all_chapters() -> List[int]:
    return sorted(_BY_CHAPTER)


def get_question(qid: str) -> Optional[dict]:
    return _BY_ID.get(qid)


def questions_by_chapter(ch: int) -> List[dict]:
    return _BY_CHAPTER.get(ch, [])


def count_by_chapter(ch: int) -> int:
    return len(_BY_CHAPTER.get(ch, []))


def total_count() -> int:
    return len(QUESTIONS)


def bank_summary() -> Dict[str, int]:
    out: Dict[str, int] = {"total": len(QUESTIONS)}
    for q in QUESTIONS:
        out[q["type"]] = out.get(q["type"], 0) + 1
    return out


def random_questions(n: int, chapters: Optional[List[int]] = None) -> List[dict]:
    """随机抽题用于自动评分测验：默认排除简答题（无法客观判分）。"""
    pool = [q for q in QUESTIONS if q["type"] != "blank"]
    if chapters:
        cset = set(chapters)
        pool = [q for q in pool if q["chapter"] in cset]
    n = min(n, len(pool))
    return random.sample(pool, n) if n > 0 else []


def _letter(idx: int) -> str:
    return string.ascii_uppercase[idx]


def check_answer(question: dict, user_answer) -> bool:
    """逐题型判题。app.py 判题唯一入口。"""
    t = question["type"]
    ans = question["answer"]
    try:
        if t in ("single", "code"):
            if user_answer is None:
                return False
            return int(user_answer) == int(ans)
        if t == "multi":
            if not user_answer:
                return False
            return set(int(x) for x in user_answer) == set(ans)
        if t == "judge":
            return bool(user_answer) == bool(ans)
        if t == "blank":
            if user_answer is None:
                return False
            u = str(user_answer).strip().lower()
            return bool(u) and any(
                u == str(a).strip().lower() or u in str(a).strip().lower()
                for a in ans)
    except (TypeError, ValueError):
        return False
    return False


def correct_answer_text(question: dict) -> str:
    t = question["type"]
    ans = question["answer"]
    if t in ("single", "code"):
        opts = question.get("options", [])
        return f"{_letter(ans)}. {opts[ans]}" if 0 <= ans < len(opts) else str(ans)
    if t == "multi":
        opts = question.get("options", [])
        return "、".join(f"{_letter(i)}. {opts[i]}" for i in sorted(ans))
    if t == "judge":
        return "正确 ✓" if ans else "错误 ✗"
    if t == "blank":
        return "\n".join(str(a) for a in ans)
    return str(ans)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("题库聚合冒烟测试")
    print("=" * 40)
    s = bank_summary()
    print(f"总题量: {s['total']}")
    for t in ("single", "multi", "judge", "blank", "code"):
        if t in s:
            print(f"  {TYPE_NAMES[t]}: {s[t]}")
    print(f"章节覆盖: {all_chapters()}")
    for ch in all_chapters():
        print(f"  第{ch}章 {CHAPTER_LABELS.get(ch,'')}: {count_by_chapter(ch)} 题")
    # 抽样：判题 + 答案展示 + 选项分布
    from collections import Counter
    dist = Counter(q["answer"] for q in QUESTIONS if q["type"] == "single")
    print("单选正确答案分布(乱序后):", dict(sorted(dist.items())))
    samp = next(q for q in QUESTIONS if q["type"] == "single")
    print("示例题:", samp["id"], samp["q"][:30])
    print("  选项:", samp["options"])
    print("  正确答案:", correct_answer_text(samp))
    print("  判题(对):", check_answer(samp, samp["answer"]))
