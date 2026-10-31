# -*- coding: utf-8 -*-
"""storage —— JSON 持久化层（无 UI 依赖）。

单文件 quiz_data.json 保存：答题记录、错题本、测验历史、界面偏好。
所有写操作接收 data 字典、原地修改并由调用方 save_data 落盘。
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "reader_data.json")

DEFAULT_DATA = {
    "quiz_attempts": {},   # {qid: {"correct":int,"wrong":int,"last":bool,"time":str}}
    "wrong_ids": [],       # 错题本（去重）
    "quiz_history": [],    # {"time","scope","total","score"}，仅存最近 50 条
    "settings": {},
}


def load_data() -> dict:
    """读取磁盘数据；文件损坏/缺字段时回退默认结构。"""
    data = copy.deepcopy(DEFAULT_DATA)
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for key in DEFAULT_DATA:
                if key in saved and isinstance(saved[key], type(DEFAULT_DATA[key])):
                    data[key] = saved[key]
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        pass
    return data


def save_data(data: dict) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def record_answer(data: dict, qid: str, is_correct: bool) -> None:
    """计数增减；答错→入错题本；答对且历史 wrong==0→移出错题本。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rec = data["quiz_attempts"].get(qid)
    if rec is None:
        rec = {"correct": 0, "wrong": 0, "last": False, "time": now}
        data["quiz_attempts"][qid] = rec
    if is_correct:
        rec["correct"] += 1
    else:
        rec["wrong"] += 1
    rec["last"] = bool(is_correct)
    rec["time"] = now

    wrong = data["wrong_ids"]
    if not is_correct:
        if qid not in wrong:
            wrong.append(qid)
    else:
        # 只有从未答错过（历史 wrong==0）才移出，防止手滑答对就洗白
        if qid in wrong and rec["wrong"] == 0:
            data["wrong_ids"] = [x for x in wrong if x != qid]


def remove_from_wrong(data: dict, qid: str) -> None:
    data["wrong_ids"] = [x for x in data["wrong_ids"] if x != qid]


def clear_wrong(data: dict) -> None:
    data["wrong_ids"] = []


def add_quiz_history(data: dict, scope: str, total: int, score: int) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["quiz_history"].append(
        {"time": now, "scope": scope, "total": total, "score": score})
    # 只保留最近 50 条
    if len(data["quiz_history"]) > 50:
        data["quiz_history"] = data["quiz_history"][-50:]


def quiz_overview(data: dict) -> dict:
    attempts = data["quiz_attempts"]
    answers = sum(v["correct"] + v["wrong"] for v in attempts.values())
    correct = sum(v["correct"] for v in attempts.values())
    accuracy = (correct / answers * 100) if answers else 0.0
    return {
        "attempted": len(attempts),
        "answers": answers,
        "correct": correct,
        "accuracy": round(accuracy, 1),
        "wrong": len(data["wrong_ids"]),
        "tests": len(data["quiz_history"]),
    }
