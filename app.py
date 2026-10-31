# -*- coding: utf-8 -*-
"""app —— Streamlit 入口：章节练习 / 随机测验 / 错题本 / 练习统计。

数据流：quiz_bank（内存题目+判题） ── UI ──> storage（JSON 持久化）。
所有对 answer 的读写都经 quiz_bank，UI 不直接碰原始 quiz_data。
"""
from __future__ import annotations

import string
import streamlit as st

import quiz_bank as qb
import storage as stx

st.set_page_config(page_title="安全生产标准化题库", page_icon="🛡️", layout="wide")

LETTERS = string.ascii_uppercase


# ---------------- 公共组件 ----------------
def _answer_widget(q, key, disabled=False):
    """按题型分发控件，返回 下标/下标列表/bool/str；未作答返回 None。"""
    t = q["type"]
    if t in ("single", "code"):
        opts = q["options"]
        labels = [f"{LETTERS[i]}. {o}" for i, o in enumerate(opts)]
        pick = st.radio("请选择", labels, key=key, disabled=disabled,
                        index=None, horizontal=False, label_visibility="collapsed")
        if pick is None:
            return None
        return labels.index(pick)
    if t == "multi":
        opts = q["options"]
        labels = [f"{LETTERS[i]}. {o}" for i, o in enumerate(opts)]
        sel = st.multiselect("请选择（可多选）", labels, key=key, disabled=disabled)
        return [labels.index(x) for x in sel]
    if t == "judge":
        pick = st.radio("你的判断", ["✅ 正确", "❌ 错误"], key=key,
                        horizontal=True, disabled=disabled,
                        label_visibility="collapsed")
        if pick is None:
            return None
        return pick == "✅ 正确"
    if t == "blank":
        return st.text_area("把你的作答要点写在这里（可选，随后与参考答案对照）",
                            key=key, height=110, disabled=disabled)
    return None


def _render_head(q, index_label=""):
    badge = qb.TYPE_NAMES.get(q["type"], q["type"])
    diff = qb.DIFFICULTY_NAMES.get(q.get("difficulty"), "")
    head = f"`{badge}`  `{diff}`  〔{q['label']}〕"
    if index_label:
        head = f"{index_label}  {head}"
    st.markdown(head)
    st.markdown(f"**{q['q']}**")


def _render_feedback(q, correct):
    if correct:
        st.success("✅ 回答正确")
    else:
        st.error("❌ 回答错误")
    st.markdown("**参考答案：**")
    st.markdown(f"> {qb.correct_answer_text(q).replace(chr(10), chr(10) + '> ')}")
    if q.get("explain") and q["type"] != "blank":
        st.info(f"解析：{q['explain']}")


def _grade_and_record(q, user, data):
    """判题+记录的唯一点：客观题走 quiz_bank.check_answer。返回 bool。"""
    ok = qb.check_answer(q, user)
    stx.record_answer(data, q["id"], ok)
    stx.save_data(data)
    return ok


# ---------------- 模式一：章节练习 ----------------
def mode_chapter(data):
    chapters = qb.all_chapters()
    opts = {ch: f"第{ch}章 · {qb.CHAPTER_LABELS.get(ch,'')}（{qb.count_by_chapter(ch)} 题）"
            for ch in chapters}
    ch = st.selectbox("选择章节", chapters, format_func=lambda c: opts[c],
                      key="ch_select")

    qs = qb.questions_by_chapter(ch)
    if "ch_idx" not in st.session_state:
        st.session_state.ch_idx = 0
    if st.session_state.get("ch_chapter") != ch:      # 切章重置游标
        st.session_state.ch_chapter = ch
        st.session_state.ch_idx = 0
    idx = min(st.session_state.ch_idx, len(qs) - 1)

    attempted = sum(1 for q in qs if q["id"] in data["quiz_attempts"])
    st.progress(attempted / len(qs) if qs else 0.0,
                text=f"本章进度：已练 {attempted}/{len(qs)}")

    q = qs[idx]
    st.markdown(f"---")
    _render_head(q, index_label=f"第 {idx + 1}/{len(qs)} 题")
    res = st.session_state.get("ch_results", {}).get(q["id"])

    if q["type"] == "blank":
        _blank_flow(q, data, res, prefix="chb")
    else:
        if res is not None:
            _answer_widget(q, key=f"ch_{q['id']}", disabled=True)
            _render_feedback(q, res["correct"])
        else:
            user = _answer_widget(q, key=f"ch_{q['id']}")
            if st.button("提交答案", key=f"chsub_{q['id']}", type="primary"):
                if user is None or (isinstance(user, list) and not user):
                    st.warning("请先作答再提交")
                else:
                    ok = _grade_and_record(q, user, data)
                    st.session_state.setdefault("ch_results", {})[q["id"]] = {
                        "user": user, "correct": ok}
                    st.rerun()

    st.markdown("---")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("⬅️ 上一题", disabled=idx <= 0):
        st.session_state.ch_idx = idx - 1
        st.rerun()
    if c2.button("下一题 ➡️", disabled=idx >= len(qs) - 1):
        st.session_state.ch_idx = idx + 1
        st.rerun()
    if c3.button("🔁 重做本题"):
        st.session_state.get("ch_results", {}).pop(q["id"], None)
        if q["type"] == "blank":
            st.session_state.get("chb_state", {}).pop(q["id"], None)
        st.rerun()
    if c4.button("🧹 重置本章记录"):
        for x in qs:
            data["quiz_attempts"].pop(x["id"], None)
            if x["id"] in data["wrong_ids"]:
                data["wrong_ids"].remove(x["id"])
        stx.save_data(data)
        st.session_state.get("ch_results", {}).clear()
        st.session_state.get("chb_state", {}).clear()
        st.rerun()


def _blank_flow(q, data, cached, prefix):
    """简答题自评流：写要点 → 显示参考答案 → 自评掌握情况。"""
    state = st.session_state.setdefault(f"{prefix}_state", {})
    cur = state.get(q["id"], {"revealed": False, "correct": None})
    own = _answer_widget(q, key=f"{prefix}_{q['id']}",
                         disabled=cur["revealed"])
    if not cur["revealed"]:
        if st.button("显示参考答案并自评", key=f"{prefix}r_{q['id']}", type="primary"):
            cur["revealed"] = True
            cur["own"] = own
            state[q["id"]] = cur
            st.rerun()
        return
    # 已展开参考答案
    if cur["correct"] is not None:                 # 已自评：展示结果
        _render_feedback(q, cur["correct"])
        return
    st.markdown("**参考答案：**")
    st.markdown("> " + qb.correct_answer_text(q).replace("\n", "\n> "))
    choice = st.radio("你的掌握情况：", ["✅ 已掌握", "❌ 未掌握 / 需复习"],
                      key=f"{prefix}c_{q['id']}", horizontal=True)
    if st.button("确认自评", key=f"{prefix}cf_{q['id']}"):
        ok = choice.startswith("✅")
        cur["correct"] = ok
        state[q["id"]] = cur
        stx.record_answer(data, q["id"], ok)
        stx.save_data(data)
        st.rerun()


# ---------------- 模式二：随机测验 ----------------
def mode_test(data):
    if "test" not in st.session_state:
        st.session_state.test = None            # 抽出的题目列表
        st.session_state.test_done = False

    if st.session_state.test is None:
        st.subheader("🎲 随机测验设置")
        with st.form("test_form"):
            n = st.slider("题目数量", 5, 100, 20)
            chs = st.multiselect("限定章节（留空=全书客观题）",
                                 qb.all_chapters(),
                                 format_func=lambda c: qb.CHAPTER_LABELS.get(c, str(c)))
            st.caption("测验为自动评分，仅含单选/多选/判断题；简答题请在章节练习或错题本中自评。")
            if st.form_submit_button("开始测验", type="primary"):
                picked = qb.random_questions(n, chs or None)
                if not picked:
                    st.warning("该范围没有可抽的题目")
                else:
                    st.session_state.test = picked
                    st.session_state.test_scope = "章节随机测验" if chs else "全书随机测验"
                    st.session_state.test_results = {}
                    st.session_state.test_done = False
                    st.rerun()
        return

    qs = st.session_state.test
    if st.session_state.test_done:
        _render_test_result(data, qs)
        return

    st.subheader(f"🎲 测验进行中（共 {len(qs)} 题）")
    results = st.session_state.setdefault("test_results", {})
    for i, q in enumerate(qs, 1):
        with st.container(border=True):
            _render_head(q, index_label=f"{i}.")
            user = _answer_widget(q, key=f"t_{q['id']}")
            results.setdefault(q["id"], None)
            results[q["id"]] = user

    if st.button("交卷并评分", type="primary"):
        unanswered = [i + 1 for i, q in enumerate(qs)
                      if not _answered(results.get(q["id"]))]
        if unanswered:
            st.warning(f"还有 {len(unanswered)} 题未作答（题号 {unanswered[:10]}…），"
                       "未答按错误计。仍要交卷吗？再点一次“交卷并评分”确认。")
            if st.session_state.get("_confirm_submit"):
                st.session_state["_confirm_submit"] = False
            else:
                st.session_state["_confirm_submit"] = True
                return
        score = 0
        for q in qs:
            ok = _grade_and_record(q, results.get(q["id"]), data)
            score += 1 if ok else 0
        st.session_state.test_score = score
        st.session_state.test_done = True
        scope = st.session_state.get("test_scope", "随机测验")
        stx.add_quiz_history(data, scope, len(qs), score)
        stx.save_data(data)
        st.rerun()


def _answered(v):
    if v is None:
        return False
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, str):
        return bool(v.strip())
    return True


def _render_test_result(data, qs):
    score = st.session_state.test_score
    total = len(qs)
    pct = score / total if total else 0
    emoji = "🏆" if pct >= 0.9 else "🎉" if pct >= 0.75 else "💪" if pct >= 0.6 else "📚"
    st.subheader(f"{emoji} 测验成绩：{score}/{total}（{pct:.0%}）")
    st.progress(pct)
    for i, q in enumerate(qs, 1):
        ok = qb.check_answer(q, st.session_state.test_results.get(q["id"]))
        icon = "✅" if ok else "❌"
        with st.expander(f"{icon} 第{i}题 · {qb.TYPE_NAMES[q['type']]} · {q['q'][:24]}…"):
            st.markdown(f"**正确答案：** {qb.correct_answer_text(q)}")
            ua = st.session_state.test_results.get(q["id"])
            st.caption(f"你的作答：{_answer_repr(q, ua)}")
    if st.button("再来一组", type="primary"):
        st.session_state.test = None
        st.session_state.test_done = False
        st.session_state.test_results = {}
        st.rerun()


def _answer_repr(q, ua):
    if ua is None or (isinstance(ua, list) and not ua):
        return "（未作答）"
    if q["type"] == "judge":
        return "正确" if ua else "错误"
    if q["type"] == "single":
        return f"{LETTERS[ua]}. {q['options'][ua]}"
    if q["type"] == "multi":
        return "、".join(f"{LETTERS[i]}. {q['options'][i]}" for i in ua)
    return str(ua)


# ---------------- 模式三：错题本 ----------------
def mode_wrong(data):
    st.subheader("❌ 错题本")
    ids = [qid for qid in data["wrong_ids"] if qb.get_question(qid)]
    if not ids:
        st.success("太棒了，错题本为空！继续保持。")
        return
    st.caption(f"共 {len(ids)} 道错题待攻克。答对且历史未再答错会自动移出。")
    if st.button("🗑️ 清空错题本"):
        stx.clear_wrong(data)
        stx.save_data(data)
        st.rerun()
    for qid in ids:
        q = qb.get_question(qid)
        with st.container(border=True):
            _render_head(q)
            rec = data["quiz_attempts"].get(qid, {})
            st.caption(f"历史：答对 {rec.get('correct',0)} / 答错 {rec.get('wrong',0)} 次")
            if q["type"] == "blank":
                _blank_flow(q, data, st.session_state.get("wr_results", {}).get(qid),
                            prefix=f"wr{qid}")
                continue
            done = st.session_state.get("wr_results", {}).get(qid)
            if done:
                _answer_widget(q, key=f"wr_{qid}", disabled=True)
                _render_feedback(q, done["correct"])
                if st.button("移出错题本", key=f"wrm_{qid}"):
                    stx.remove_from_wrong(data, qid)
                    stx.save_data(data)
                    st.session_state["wr_results"].pop(qid, None)
                    st.rerun()
            else:
                user = _answer_widget(q, key=f"wr_{qid}")
                if st.button("提交", key=f"wrsub_{qid}", type="primary"):
                    if not _answered(user):
                        st.warning("请先作答")
                    else:
                        ok = _grade_and_record(q, user, data)
                        st.session_state.setdefault("wr_results", {})[qid] = {
                            "user": user, "correct": ok}
                        if ok and data["quiz_attempts"][qid]["wrong"] == 0:
                            stx.remove_from_wrong(data, qid)
                            stx.save_data(data)
                        st.rerun()


# ---------------- 模式四：统计 ----------------
def mode_stat(data):
    st.subheader("📊 练习统计")
    ov = stx.quiz_overview(data)
    m = st.columns(5)
    m[0].metric("已练题目", ov["attempted"])
    m[1].metric("累计作答", ov["answers"])
    m[2].metric("累计答对", ov["correct"])
    m[3].metric("正确率", f"{ov['accuracy']}%")
    m[4].metric("待攻克错题", ov["wrong"])

    st.markdown("#### 各章练习进度")
    for ch in qb.all_chapters():
        qs = qb.questions_by_chapter(ch)
        done = sum(1 for q in qs if q["id"] in data["quiz_attempts"])
        ratio = done / len(qs) if qs else 0
        st.progress(ratio, text=f"第{ch}章 {qb.CHAPTER_LABELS.get(ch,'')}：已练 {done}/{len(qs)}")

    st.markdown("#### 最近测验")
    hist = data["quiz_history"][-10:][::-1]
    if not hist:
        st.caption("暂无测验记录")
    for h in hist:
        acc = (h["score"] / h["total"] * 100) if h["total"] else 0
        st.caption(f"{h['time']} · {h['scope']} · {h['score']}/{h['total']}（{acc:.0f}%）")


# ---------------- 主页 ----------------
def main():
    data = stx.load_data()
    s = qb.bank_summary()
    st.sidebar.title("🛡️ 安全生产标准化题库")
    st.sidebar.caption(f"共 {s['total']} 题 · 单选 {s.get('single',0)} · "
                       f"多选 {s.get('multi',0)} · 判断 {s.get('judge',0)} · "
                       f"简答 {s.get('blank',0)}")
    st.sidebar.markdown("---")
    mode = st.sidebar.radio("练习模式",
                            ["📖 章节练习", "🎲 随机测验", "❌ 错题本", "📊 练习统计"])

    if mode == "📖 章节练习":
        mode_chapter(data)
    elif mode == "🎲 随机测验":
        mode_test(data)
    elif mode == "❌ 错题本":
        mode_wrong(data)
    else:
        mode_stat(data)


if __name__ == "__main__":
    main()
