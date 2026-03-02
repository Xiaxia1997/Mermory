#!/usr/bin/env python3
import argparse
import csv
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "planner.db"
PLAN_PATH = BASE_DIR / "plan.yaml"

CATEGORY_HELP = (
    "类别说明: H0=工作硬交付(有deadline/阻塞置顶) | "
    "P1=LLM技术深度 | P2=Leetcode不断档 | P3=项目证据 | P4=简历"
)
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def current_week_start() -> str:
    return monday_of(date.today()).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def print_header() -> None:
    print("\n" + "=" * 80)
    print(CATEGORY_HELP)
    print("=" * 80)


def parse_hhmm(s: str) -> time:
    return datetime.strptime(s.strip(), "%H:%M").time()


def ask_choice_yn(prompt: str, default: str = "y") -> str:
    default = default.lower()
    while True:
        v = input(prompt).strip().lower()
        if not v:
            return default
        if v in ("y", "n"):
            return v
        print("请输入 y 或 n。")


def ask_float(prompt: str, default: Optional[float] = None) -> float:
    while True:
        v = input(prompt).strip()
        if not v and default is not None:
            return default
        try:
            return float(v)
        except ValueError:
            print("请输入数字，例如 1.5")


def overlap_hours(start: datetime, end: datetime, bstart: time, bend: time) -> float:
    if end <= start:
        return 0.0
    bs = datetime.combine(start.date(), bstart)
    be = datetime.combine(start.date(), bend)
    s = max(start, bs)
    e = min(end, be)
    if e <= s:
        return 0.0
    return (e - s).total_seconds() / 3600.0


def estimate_hours(task_text: str) -> float:
    text = task_text.lower()
    mins = 0
    h_match = re.findall(r"(\d+(?:\.\d+)?)\s*h", text)
    m_match = re.findall(r"(\d+)\s*min", text)
    cn_min_match = re.findall(r"(\d+)\s*分", task_text)

    if h_match:
        mins += int(float(h_match[0]) * 60)
    if m_match:
        mins += int(m_match[0])
    elif cn_min_match:
        mins += int(cn_min_match[0])

    q_match = re.search(r"(\d+)题", task_text)
    if q_match:
        qn = int(q_match.group(1))
        each = 40 if mins == 0 else mins
        mins = qn * each

    if "限时" in task_text and mins == 0:
        mins += 40

    if mins == 0:
        if task_text.startswith("推导笔记"):
            return 3.0
        if task_text.startswith("实验"):
            return 4.0
        if task_text.startswith("Q&A"):
            return 2.0
        if "简历" in task_text:
            return 1.5
        return 2.0
    return round(mins / 60.0, 1)


def bootstrap_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS weekly_state (
                week_start TEXT PRIMARY KEY,
                energy INTEGER,
                deadline TEXT,
                p1_status TEXT,
                p2_status TEXT,
                p3_status TEXT,
                p4_status TEXT,
                avail_weekday TEXT,
                avail_weekend TEXT,
                notes TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                category TEXT NOT NULL,
                task TEXT NOT NULL,
                est_hours REAL,
                status TEXT NOT NULL,
                inherited_from TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS forced_deliverables (
                week_start TEXT PRIMARY KEY,
                p1_note TEXT,
                p1_exp TEXT,
                p3_exp TEXT,
                resume TEXT,
                h0_delivery TEXT
            );
            CREATE TABLE IF NOT EXISTS week_progress (
                week_start TEXT PRIMARY KEY,
                p1_done INTEGER,
                p2_done INTEGER,
                p3_done INTEGER,
                resume_done INTEGER
            );
            CREATE TABLE IF NOT EXISTS prompt_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT,
                generated_at TEXT,
                prompt_text TEXT,
                today_hours REAL,
                today_energy INTEGER,
                today_deadline TEXT
            );
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(forced_deliverables)").fetchall()]
        if "h0_delivery" not in cols:
            conn.execute("ALTER TABLE forced_deliverables ADD COLUMN h0_delivery TEXT")


def load_plan() -> Dict:
    data = {"yamlmeta": {}, "weeks": {}}
    section = None
    current_week = None
    with PLAN_PATH.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            if line.startswith("yamlmeta:"):
                section = "yamlmeta"
                current_week = None
                continue
            if line.startswith("weeks:"):
                section = "weeks"
                current_week = None
                continue
            if section == "yamlmeta" and line.startswith("  "):
                k, v = line.strip().split(":", 1)
                data["yamlmeta"][k.strip()] = v.strip().strip('"')
                continue
            if section == "weeks":
                if line.startswith("  ") and line.strip().endswith(":") and line.strip()[:-1].isdigit():
                    current_week = int(line.strip()[:-1])
                    data["weeks"][current_week] = {}
                    continue
                if current_week is not None and line.startswith("    "):
                    k, v = line.strip().split(":", 1)
                    data["weeks"][current_week][k.strip()] = v.strip().strip('"')
    return data


def roadmap_context(plan: Dict, ws: str) -> Dict:
    start = datetime.fromisoformat(plan["yamlmeta"]["start_week"]).date()
    cur = datetime.fromisoformat(ws).date()
    idx = ((cur - start).days // 7) + 1
    idx = max(1, min(6, idx))
    return {"week_idx": idx, "week": plan["weeks"][idx]}


def ensure_weekly_state(conn: sqlite3.Connection, ws: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM weekly_state WHERE week_start=?", (ws,)).fetchone()
    if row:
        return row
    conn.execute(
        """INSERT INTO weekly_state
        (week_start, energy, deadline, p1_status, p2_status, p3_status, p4_status, avail_weekday, avail_weekend, notes, created_at)
        VALUES (?, 3, '无', '未开始', '未开始', '未开始', '未开始', '2h', '4h', '', ?)""",
        (ws, now_ts()),
    )
    return conn.execute("SELECT * FROM weekly_state WHERE week_start=?", (ws,)).fetchone()


def ensure_default_deliverables(conn: sqlite3.Connection, ws: str, week_item: Dict) -> None:
    existing = conn.execute("SELECT week_start FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
    if existing:
        return
    conn.execute(
        """INSERT INTO forced_deliverables(week_start, p1_note, p1_exp, p3_exp, resume, h0_delivery)
        VALUES(?,?,?,?,?,?)""",
        (
            ws,
            week_item.get("d_p1_note", week_item.get("p1_note", "")),
            week_item.get("d_p1_exp", week_item.get("p1_exp", "")),
            week_item.get("d_p3_exp", week_item.get("p3", "")),
            week_item.get("d_resume", week_item.get("resume", "")),
            week_item.get("d_h0", "无"),
        ),
    )


def cmd_init(_: argparse.Namespace) -> None:
    ws = current_week_start()
    print_header()
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        print(f"本周起始: {ws} (init只管理状态，不录入任务)")
        energy = int(ask_float("本周精力(1-5): ", 3))
        deadline = input("工作deadline/阻塞(无则填'无'): ").strip() or "无"
        p1 = input("P1当前进度: ").strip() or "未开始"
        p2 = input("P2当前进度: ").strip() or "未开始"
        p3 = input("P3当前进度: ").strip() or "未开始"
        p4 = input("P4当前进度: ").strip() or "未开始"
        awd = input("工作日可用时段(如 20:30-22:30): ").strip() or "?"
        awe = input("周末可用时段(如 09:00-12:00,20:00-22:00): ").strip() or "?"
        notes = input("备注(可空): ").strip()
        conn.execute(
            """UPDATE weekly_state SET energy=?, deadline=?, p1_status=?, p2_status=?, p3_status=?, p4_status=?,
               avail_weekday=?, avail_weekend=?, notes=? WHERE week_start=?""",
            (energy, deadline, p1, p2, p3, p4, awd, awe, notes, ws),
        )
    print("✅ init完成")


def cmd_rollover(_: argparse.Namespace) -> None:
    ws = current_week_start()
    prev_ws = (datetime.fromisoformat(ws).date() - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        c = conn.execute(
            "SELECT COUNT(1) c FROM tasks WHERE week_start=? AND inherited_from=?", (ws, prev_ws)
        ).fetchone()["c"]
        if c:
            print(f"⚠️ 本周已存在继承任务({c}条)，跳过rollover")
            return
        rows = conn.execute(
            "SELECT category, task, est_hours FROM tasks WHERE week_start=? AND status IN ('todo','backlog')",
            (prev_ws,),
        ).fetchall()
        for r in rows:
            conn.execute(
                """INSERT INTO tasks(week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                   VALUES(?,?,?,?, 'todo', ?, ?, ?)""",
                (ws, r["category"], r["task"], r["est_hours"], prev_ws, now_ts(), now_ts()),
            )
    print(f"✅ rollover完成: 继承 {len(rows)} 条任务")


def cmd_add(_: argparse.Namespace) -> None:
    ws = current_week_start()
    plan = load_plan()
    rc = roadmap_context(plan, ws)
    wk = rc["week"]
    print_header()
    print(f"本周路线图主题: Week {rc['week_idx']} - {wk['theme']}")
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        ensure_default_deliverables(conn, ws, wk)
        candidates = [
            ("P1", f"推导笔记: {wk['p1_note']}"),
            ("P1", f"实验: {wk['p1_exp']}"),
            ("P1", f"Q&A: {wk['p1_qa']}"),
            ("P2", wk["p2"]),
            ("P3", wk["p3"]),
            ("P4", wk["resume"]),
        ]
        for cat, text in candidates:
            est_guess = estimate_hours(text)
            yn = ask_choice_yn(f"加入任务池？[{cat}] {text} (y/n): ")
            if yn == "n":
                continue
            conn.execute(
                """INSERT INTO tasks(week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                   VALUES(?,?,?,?,'todo',NULL,?,?)""",
                (ws, cat, text, est_guess, now_ts(), now_ts()),
            )
            print(f"  已加入，预计时长自动估算: {est_guess}h")
        print("补充自由任务（空行结束）")
        while True:
            name = input("任务名: ").strip()
            if not name:
                break
            cat = (input("类别(H0/P1/P2/P3/P4): ").strip().upper() or "P2")
            est = ask_float("预计时长(小时，默认1): ", 1.0)
            conn.execute(
                """INSERT INTO tasks(week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                   VALUES(?,?,?,?,'todo',NULL,?,?)""",
                (ws, cat, name, est, now_ts(), now_ts()),
            )
    print("✅ add完成")


def cmd_deliverables(args: argparse.Namespace) -> None:
    ws = current_week_start()
    print_header()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
        if not row:
            plan = load_plan()
            wk = roadmap_context(plan, ws)["week"]
            ensure_default_deliverables(conn, ws, wk)
            row = conn.execute("SELECT * FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()

        if args.show:
            print(f"P1推导笔记: {row['p1_note']}")
            print(f"P1实验: {row['p1_exp']}")
            print(f"P3实验闭环: {row['p3_exp']}")
            print(f"简历: {row['resume']}")
            print(f"H0工作交付(在线刷新): {row['h0_delivery']}")
            return

        if args.edit:
            p1n = input(f"P1推导笔记[{row['p1_note']}]: ").strip() or row["p1_note"]
            p1e = input(f"P1实验[{row['p1_exp']}]: ").strip() or row["p1_exp"]
            p3e = input(f"P3实验闭环[{row['p3_exp']}]: ").strip() or row["p3_exp"]
            res = input(f"简历[{row['resume']}]: ").strip() or row["resume"]
            conn.execute(
                "UPDATE forced_deliverables SET p1_note=?, p1_exp=?, p3_exp=?, resume=? WHERE week_start=?",
                (p1n, p1e, p3e, res, ws),
            )
            print("✅ 交付物(非H0)已更新")
            return

        print("请使用 deliverables --show 或 deliverables --edit")


def cmd_refresh_h0(_: argparse.Namespace) -> None:
    ws = current_week_start()
    print_header()
    with get_conn() as conn:
        st = ensure_weekly_state(conn, ws)
        current = st["deadline"] or "无"
        ddl = input(f"刷新H0工作交付/阻塞[{current}]: ").strip() or current
        conn.execute("UPDATE weekly_state SET deadline=? WHERE week_start=?", (ddl, ws))

        row = conn.execute("SELECT week_start FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
        if not row:
            plan = load_plan()
            wk = roadmap_context(plan, ws)["week"]
            ensure_default_deliverables(conn, ws, wk)
        conn.execute("UPDATE forced_deliverables SET h0_delivery=? WHERE week_start=?", (ddl, ws))
    print("✅ H0已在线刷新")


def update_week_progress(conn: sqlite3.Connection, ws: str) -> sqlite3.Row:
    checks = {}
    for cat, k in (("P1", "p1_done"), ("P2", "p2_done"), ("P3", "p3_done"), ("P4", "resume_done")):
        n = conn.execute(
            "SELECT COUNT(1) c FROM tasks WHERE week_start=? AND category=? AND status='done'", (ws, cat)
        ).fetchone()["c"]
        checks[k] = 1 if n > 0 else 0
    conn.execute(
        """INSERT INTO week_progress(week_start,p1_done,p2_done,p3_done,resume_done)
           VALUES(?,?,?,?,?)
           ON CONFLICT(week_start) DO UPDATE SET
           p1_done=excluded.p1_done,p2_done=excluded.p2_done,p3_done=excluded.p3_done,resume_done=excluded.resume_done""",
        (ws, checks["p1_done"], checks["p2_done"], checks["p3_done"], checks["resume_done"]),
    )
    return conn.execute("SELECT * FROM week_progress WHERE week_start=?", (ws,)).fetchone()


def week_date_range(ws: str) -> str:
    d = datetime.fromisoformat(ws).date()
    return f"{d.isoformat()} ~ {(d + timedelta(days=6)).isoformat()}"


def calc_today_hours(offwork_hhmm: str) -> float:
    now = datetime.now()
    off = datetime.combine(now.date(), parse_hhmm(offwork_hhmm))
    if off <= now:
        return 0.0
    total = (off - now).total_seconds() / 3600.0
    total -= overlap_hours(now, off, time(12, 0), time(14, 0))
    total -= overlap_hours(now, off, time(18, 0), time(19, 0))
    return round(max(total, 0.0), 2)


def cmd_generate(_: argparse.Namespace) -> None:
    ws = current_week_start()
    plan = load_plan()
    today = date.today()
    weekday_cn = WEEKDAY_CN[today.weekday()]

    with get_conn() as conn:
        state = ensure_weekly_state(conn, ws)
        rc = roadmap_context(plan, ws)
        ensure_default_deliverables(conn, ws, rc["week"])

        progress = update_week_progress(conn, ws)
        fd = conn.execute("SELECT * FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
        tasks = conn.execute(
            "SELECT id, category, task, est_hours, status, inherited_from FROM tasks WHERE week_start=? ORDER BY id", (ws,)
        ).fetchall()

        print_header()
        offwork = input("今天下班时间(HH:MM，例如19:00): ").strip() or "19:00"
        today_hours = calc_today_hours(offwork)
        print(f"自动计算今日剩余可用时间: {today_hours}h (已扣除12:00-14:00午休与18:00-19:00晚餐重叠时段)")
        today_energy = int(ask_float("今天精力(1-5): ", float(state["energy"] or 3)))
        today_ddl = input("今天有无硬截止任务(无 / 有+任务id): ").strip() or "无"

        roadmap_block = (
            f"【6周路线图定位】\n"
            f"- 当前周序号: Week {rc['week_idx']}\n"
            f"- 本周主题(P1): {rc['week']['theme']}\n"
            f"- 本周P1注入: {rc['week']['p1_note']}\n"
        )
        tasks_text = "\n".join(
            f"- [{t['id']}] {t['category']} | {t['task']} | {t['status']} | {t['est_hours']}h"
            + (f" | inherited_from={t['inherited_from']}" if t["inherited_from"] else "")
            for t in tasks
        ) or "- (空)"

        avail = {"weekday": state["avail_weekday"] or "?", "weekend": state["avail_weekend"] or "?"}

        prompt = f"""你是我的"周计划与优先级裁判"，请严格执行，不要鸡汤，不要扩展无关内容；不确定就写清假设。

【优先级（高→低）】
H0 工作硬交付（有deadline/阻塞必须置顶）
P1 LLM技术深度（必须每周产出：1份可复述推导笔记 + 1个最小实验数据结果 + 10条面试Q&A）
   主题范围：Transformer/Attention推导；SFT/RLHF/DPO流程；推理优化(KV cache/量化/投机采样/vLLM)；RAG vs Fine-tuning选型逻辑
P2 Leetcode不断档（工作日最小30-45min；每周>=1次限时；错题复盘）
P3 项目证据积累（每周至少1次实验闭环：改动→评测→结论；持续失败分类与指标）
P4 简历（本阶段目标：简历v1可投，素材随证据迭代）

【硬约束】
1) 若存在工作硬deadline/阻塞：H0必须是Top1，且压缩其他任务为"最小动作"不断档。
2) 本周最多输出Top5任务；其余进入Backlog，但仍按优先级排序标注。
3) 每个Top任务必须给：DoD + Next Action + 预计时长 + 精力需求（低/中/高）+ 风险与备选方案。
4) P1交付物三件套缺一不可：推导笔记 + 实验结果 + 10条Q&A。
5) 输出必须可执行：给出具体时间块建议，不要泛泛"多学习"。

{roadmap_block}

【本周输入】
- 日期范围：{week_date_range(ws)}
- 可用时段：工作日 {avail['weekday']} | 周末 {avail['weekend']}
- 精力（周维度）：{state['energy']}/5
- 工作deadline/阻塞：{state['deadline']}
- 当前进度：
  - P1：{state['p1_status']}
  - P2：{state['p2_status']}
  - P3：{state['p3_status']}
  - P4：{state['p4_status']}
- week_progress(自动推断): P1={progress['p1_done']} P2={progress['p2_done']} P3={progress['p3_done']} Resume={progress['resume_done']}
- 任务池：
{tasks_text}
- 强制交付物：
  - P1推导笔记：{fd['p1_note']}
  - P1实验：{fd['p1_exp']}
  - P3实验闭环：{fd['p3_exp']}
  - 简历：{fd['resume']}
  - H0工作交付(在线刷新)：{fd['h0_delivery']}
"""
        if state["notes"]:
            prompt += f"- 备注：{state['notes']}\n"
        prompt += f"""
【你的输出要求（严格按此结构）】
=== 段一：本周计划 ===
1) 本周模式判断（常态/被交付压顶）与关键假设（≤6行）
2) 本周Top5任务表格：排名｜任务｜类别｜预计时长｜精力｜DoD｜Next Action｜风险&备选
3) 本周日程块建议（至少3个深度工作块，格式：日期+时间段+任务）
4) 最小动作清单（P1/P2/P3各≤30min的不断档动作）
5) Backlog（可延期任务，每条一句理由）

=== 段二：今日排序 ===
【今日输入】
- 今天：{today.strftime('%Y-%m-%d')} {weekday_cn}
- 剩余可用时间：{today_hours}h
- 今日精力：{today_energy}/5
- 今日硬截止：{today_ddl}

【今日排序要求】
按优先级+时间约束给出今天执行顺序，每条格式：
序号. 任务名 | 预计用时 | 为什么今天做这个
总时长不超过{today_hours}h，精力{today_energy}/5时相应调整认知负荷分配。
"""
        conn.execute(
            "INSERT INTO prompt_log(week_start, generated_at, prompt_text, today_hours, today_energy, today_deadline) VALUES(?,?,?,?,?,?)",
            (ws, now_ts(), prompt, today_hours, today_energy, today_ddl),
        )
    print("\n[说明] generate 输出的是“一版Prompt”，内部包含两段：段一(周计划)+段二(今日排序)。")
    print("\n" + prompt)


def cmd_done(args: argparse.Namespace) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (args.status, now_ts(), args.id))
    print(f"✅ 任务[{args.id}] -> {args.status}")


def cmd_list(_: argparse.Namespace) -> None:
    ws = current_week_start()
    with get_conn() as conn:
        st = ensure_weekly_state(conn, ws)
        tasks = conn.execute(
            "SELECT id, category, task, est_hours, status, inherited_from FROM tasks WHERE week_start=? ORDER BY id", (ws,)
        ).fetchall()
        fd = conn.execute("SELECT * FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
    print_header()
    print(f"week_start={ws} | energy={st['energy']} | deadline={st['deadline']}")
    print(f"P1={st['p1_status']} | P2={st['p2_status']} | P3={st['p3_status']} | P4={st['p4_status']}")
    print("任务池:")
    for t in tasks:
        inherit = f" | inherited_from={t['inherited_from']}" if t["inherited_from"] else ""
        print(f"  [{t['id']}] {t['category']} | {t['task']} | {t['status']} | {t['est_hours']}h{inherit}")
    if not tasks:
        print("  (空)")
    if fd:
        print(f"交付物: P1笔记={fd['p1_note']} | P1实验={fd['p1_exp']} | P3={fd['p3_exp']} | 简历={fd['resume']} | H0={fd['h0_delivery']}")


def cmd_roadmap(_: argparse.Namespace) -> None:
    plan = load_plan()
    ws = current_week_start()
    rc = roadmap_context(plan, ws)
    print(f"{plan['yamlmeta']['title']} (start_week={plan['yamlmeta']['start_week']})")
    for i in range(1, 7):
        wk = plan["weeks"][i]
        prefix = "👉" if i == rc["week_idx"] else "  "
        print(f"{prefix} Week {i}: {wk['theme']}")


def cmd_history(_: argparse.Namespace) -> None:
    with get_conn() as conn:
        rows = conn.execute("SELECT week_start,created_at FROM weekly_state ORDER BY week_start DESC").fetchall()
    for r in rows:
        print(f"- {r['week_start']} (created_at={r['created_at']})")


def cmd_export(_: argparse.Namespace) -> None:
    out = BASE_DIR / "tasks.csv"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id,week_start,category,task,est_hours,status,inherited_from,created_at,updated_at FROM tasks ORDER BY id"
        ).fetchall()
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "week_start", "category", "task", "est_hours", "status", "inherited_from", "created_at", "updated_at"])
        for r in rows:
            w.writerow([r[k] for k in r.keys()])
    print(f"✅ 已导出 {out}")


def cmd_import(_: argparse.Namespace) -> None:
    src = BASE_DIR / "tasks.csv"
    if not src.exists():
        raise FileNotFoundError(f"未找到 {src}")
    with src.open("r", encoding="utf-8") as f, get_conn() as conn:
        reader = csv.DictReader(f)
        conn.execute("DELETE FROM tasks")
        for r in reader:
            conn.execute(
                "INSERT INTO tasks(id,week_start,category,task,est_hours,status,inherited_from,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    int(r["id"]),
                    r["week_start"],
                    r["category"],
                    r["task"],
                    float(r["est_hours"]) if r["est_hours"] else None,
                    r["status"],
                    r["inherited_from"] or None,
                    r["created_at"],
                    r["updated_at"],
                ),
            )
    print(f"✅ 已导入 {src}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="weekly planner")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("rollover")
    add = sub.add_parser("add")
    add.add_argument("--batch", action="store_true", default=True)

    d = sub.add_parser("deliverables")
    d.add_argument("--show", action="store_true")
    d.add_argument("--edit", action="store_true")

    sub.add_parser("refresh-h0")
    sub.add_parser("generate")
    done = sub.add_parser("done")
    done.add_argument("id", type=int)
    done.add_argument("status", nargs="?", default="done", choices=["done", "backlog", "dropped"])
    sub.add_parser("list")
    sub.add_parser("roadmap")
    sub.add_parser("history")
    sub.add_parser("export")
    sub.add_parser("import")
    return p


def main() -> None:
    bootstrap_db()
    args = build_parser().parse_args()
    fn = {
        "init": cmd_init,
        "rollover": cmd_rollover,
        "add": cmd_add,
        "deliverables": cmd_deliverables,
        "refresh-h0": cmd_refresh_h0,
        "generate": cmd_generate,
        "done": cmd_done,
        "list": cmd_list,
        "roadmap": cmd_roadmap,
        "history": cmd_history,
        "export": cmd_export,
        "import": cmd_import,
    }[args.cmd]
    fn(args)


if __name__ == "__main__":
    main()
