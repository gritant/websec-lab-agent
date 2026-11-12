"""WebSec Lab Agent · 运行回放与知识点界面。

启动：python main.py ui   （等价于 streamlit run ui/app.py）

三种观看方式：
- 步骤回放：每步展示 思考 -> 工具调用 -> 观察（含原始 HTTP 报文）
- 知识卡片：按漏洞类别讲解原理、常用 payload 与防御（docs/knowledge.yaml）
- 实时跟随：运行中开启自动刷新即可"直播"Agent 干活
"""

import glob
import json
import os
import sys
import time

import streamlit as st
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RUNS_DIR = os.path.join(ROOT, "runs")
KNOWLEDGE_PATH = os.path.join(ROOT, "docs", "knowledge.yaml")

st.set_page_config(page_title="WebSec Lab Agent 回放", page_icon="🛡️", layout="wide")


@st.cache_data(ttl=3)
def list_runs():
    runs = []
    for f in sorted(glob.glob(os.path.join(RUNS_DIR, "*.json")), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                runs.append(json.load(fh))
        except Exception:
            pass
    return runs


@st.cache_data
def load_knowledge():
    with open(KNOWLEDGE_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def render_knowledge(category):
    card = load_knowledge().get(category)
    if not card:
        return
    with st.expander("📖 知识卡片 —— 这类漏洞的原理与套路", expanded=True):
        st.markdown(f"**{card.get('name', category)}**")
        st.markdown(card.get("principle", ""))
        payloads = card.get("payloads") or []
        if payloads:
            st.markdown("**常用 payload**")
            for p in payloads:
                st.code(p, language="text")
        tips = card.get("tips") or []
        if tips:
            st.markdown("**测试思路**")
            for t in tips:
                st.markdown(f"- {t}")
        if card.get("defense"):
            st.info(f"**防御** {card['defense']}")


# ---------- 侧边栏：运行选择 ----------
runs = list_runs()
if not runs:
    st.warning("还没有运行记录。先跑一次冒烟测试：`python main.py smoke`")
    st.stop()

run = st.sidebar.selectbox(
    "选择运行记录",
    runs,
    format_func=lambda r: (
        f"{'✅' if r.get('solved') else '❌'} {r['lab_id']} · {r['mode']} · {r['started_at']}"
    ),
)

st.sidebar.markdown("---")
st.sidebar.markdown(f"**题目**: {run.get('lab_title', run['lab_id'])}")
st.sidebar.markdown(f"**类别**: `{run.get('category', '?')}`　**模式**: `{run.get('mode')}`")
st.sidebar.markdown(f"**目标**: `{run.get('base_url')}`")
st.sidebar.markdown(
    f"**状态**: {'✅ 已通关' if run.get('solved') else '❌ 未通关'}（{run.get('status')}）"
)

m = run.get("metrics", {})
c1, c2 = st.sidebar.columns(2)
c1.metric("步骤", m.get("steps", "-"))
c2.metric("HTTP请求", m.get("http_requests", "-"))
c3, c4 = st.sidebar.columns(2)
c3.metric("LLM调用", m.get("llm_calls", "-"))
c4.metric("耗时(s)", m.get("duration_sec", "-"))

if run.get("summary"):
    st.sidebar.success(run["summary"])

if run.get("status") == "running":
    if st.sidebar.checkbox("实时跟随（2 秒刷新）"):
        time.sleep(2)
        st.rerun()

# ---------- 主区：步骤回放 ----------
st.title("🛡️ Agent 渗透测试回放")
st.caption("每一步 = 看到什么(页面快照) → 想什么(思考) → 做什么(请求) → 得到什么(响应)")

steps = run.get("steps", [])
if not steps:
    st.info("该记录还没有步骤。")
    st.stop()

labels = [
    f"Step {s['step']}: {s['action'] or '(格式错误)'}"
    + ("　🎯" if s["action"] == "check_solved" and '"solved": true' in s["observation"].lower() else "")
    for s in steps
]
idx = st.selectbox("步骤", range(len(steps)), format_func=lambda i: labels[i])
step = steps[idx]

st.markdown(f"### Step {step['step']}　`{step['action'] or '?'}`")

if step.get("status") == "format_error":
    st.warning("⚠️ 输出格式错误，系统已要求模型重试")

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 🧠 Agent 思考")
    if step.get("thought"):
        st.info(step["thought"])
    else:
        st.caption("（无）")
    st.markdown("#### 🔧 工具调用")
    ai = step.get("action_input") or {}
    if ai:
        st.code(json.dumps(ai, ensure_ascii=False, indent=2), language="json")
    else:
        st.caption("（无参数）")

with col2:
    st.markdown("#### 👁 观察结果（Agent 看到的）")
    obs = step.get("observation") or ""
    if obs:
        st.text(obs[:1500] + ("…[截断]" if len(obs) > 1500 else ""))
    else:
        st.caption("（无）")

traffic = step.get("traffic")
if traffic:
    st.markdown("#### 🌐 原始 HTTP 报文")
    a, b = st.columns(2)
    with a:
        with st.expander("→ 请求", expanded=False):
            st.code(traffic.get("request", ""), language="http")
    with b:
        with st.expander("← 响应", expanded=False):
            st.code(traffic.get("response", ""), language="http")
else:
    st.caption("（本步骤无 HTTP 流量）")

st.markdown("---")
render_knowledge(run.get("category"))
