#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


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


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                resume TEXT
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


def load_plan() -> Dict:
    """Minimal YAML loader for current plan.yaml schema to avoid external deps."""
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


def current_week_start() -> str:
    return monday_of(date.today()).isoformat()


def print_header() -> None:
    print("\n" + "=" * 80)
    print(CATEGORY_HELP)
    print("=" * 80)


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


def cmd_init(args: argparse.Namespace) -> None:
    ws = current_week_start()
    print_header()
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        print(f"本周起始: {ws} (init只管理状态，不录入任务)")
        energy = int(input("本周精力(1-5): ").strip() or "3")
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


def cmd_rollover(args: argparse.Namespace) -> None:
    ws = current_week_start()
    prev_ws = (datetime.fromisoformat(ws).date() - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        existing = conn.execute(
            "SELECT COUNT(1) AS c FROM tasks WHERE week_start=? AND inherited_from=?", (ws, prev_ws)
        ).fetchone()["c"]
        if existing:
            print(f"⚠️ 本周已存在继承任务({existing}条)，跳过rollover")
            return

        rows = conn.execute(
            "SELECT category, task, est_hours, status FROM tasks WHERE week_start=? AND status IN ('todo','backlog')",
            (prev_ws,),
        ).fetchall()
        for r in rows:
            conn.execute(
                """INSERT INTO tasks (week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'todo', ?, ?, ?)""",
                (ws, r["category"], r["task"], r["est_hours"], prev_ws, now_ts(), now_ts()),
            )
        print(f"✅ rollover完成: 继承 {len(rows)} 条任务 (from {prev_ws})")


def roadmap_context(plan: Dict, ws: str) -> Dict:
    start = datetime.fromisoformat(plan["yamlmeta"]["start_week"]).date()
    cur = datetime.fromisoformat(ws).date()
    n = ((cur - start).days // 7) + 1
    n = max(1, min(6, n))
    wk = plan["weeks"].get(n) or plan["weeks"].get(str(n))
    return {"week_idx": n, "week": wk}


def cmd_add(args: argparse.Namespace) -> None:
    ws = current_week_start()
    plan = load_plan()
    rc = roadmap_context(plan, ws)
    wk = rc["week"]
    print_header()
    print(f"本周路线图主题: Week {rc['week_idx']} - {wk['theme']}")

    candidates = [
        ("P1", f"推导笔记: {wk['p1_note']}"),
        ("P1", f"实验: {wk['p1_exp']}"),
        ("P1", f"Q&A: {wk['p1_qa']}"),
        ("P2", wk["p2"]),
        ("P3", wk["p3"]),
        ("P4", wk["resume"]),
    ]
    with get_conn() as conn:
        ensure_weekly_state(conn, ws)
        for cat, text in candidates:
            ans = (input(f"加入任务池？[{cat}] {text} (y/n): ").strip().lower() or "y")
            if ans != "y":
                continue
            est = float(input("预计时长(小时): ").strip() or "1")
            conn.execute(
                """INSERT INTO tasks(week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'todo', NULL, ?, ?)""",
                (ws, cat, text, est, now_ts(), now_ts()),
            )

        print("补充自由任务（空行结束）")
        while True:
            name = input("任务名: ").strip()
            if not name:
                break
            cat = (input("类别(H0/P1/P2/P3/P4): ").strip().upper() or "P2")
            est = float(input("预计时长(小时): ").strip() or "1")
            conn.execute(
                """INSERT INTO tasks(week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'todo', NULL, ?, ?)""",
                (ws, cat, name, est, now_ts(), now_ts()),
            )
    print("✅ add完成")


def cmd_deliverables(args: argparse.Namespace) -> None:
    ws = current_week_start()
    print_header()
    with get_conn() as conn:
        p1n = input("P1推导笔记交付物: ").strip()
        p1e = input("P1实验交付物: ").strip()
        p3e = input("P3实验闭环交付物: ").strip()
        res = input("简历交付物: ").strip()
        conn.execute(
            """INSERT INTO forced_deliverables(week_start, p1_note, p1_exp, p3_exp, resume)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET p1_note=excluded.p1_note, p1_exp=excluded.p1_exp,
            p3_exp=excluded.p3_exp, resume=excluded.resume""",
            (ws, p1n, p1e, p3e, res),
        )
    print("✅ deliverables完成")


def update_week_progress(conn: sqlite3.Connection, ws: str) -> sqlite3.Row:
    checks = {}
    for cat, k in [("P1", "p1_done"), ("P2", "p2_done"), ("P3", "p3_done"), ("P4", "resume_done")]:
        cnt = conn.execute(
            "SELECT COUNT(1) AS c FROM tasks WHERE week_start=? AND category=? AND status='done'", (ws, cat)
        ).fetchone()["c"]
        checks[k] = 1 if cnt > 0 else 0
    conn.execute(
        """INSERT INTO week_progress(week_start, p1_done, p2_done, p3_done, resume_done)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(week_start) DO UPDATE SET p1_done=excluded.p1_done, p2_done=excluded.p2_done,
        p3_done=excluded.p3_done, resume_done=excluded.resume_done""",
        (ws, checks["p1_done"], checks["p2_done"], checks["p3_done"], checks["resume_done"]),
    )
    return conn.execute("SELECT * FROM week_progress WHERE week_start=?", (ws,)).fetchone()


def week_date_range(ws: str) -> str:
    d = datetime.fromisoformat(ws).date()
    return f"{d.isoformat()} ~ {(d + timedelta(days=6)).isoformat()}"


def cmd_generate(args: argparse.Namespace) -> None:
    ws = current_week_start()
    plan = load_plan()
    today = date.today()
    weekday_cn = WEEKDAY_CN[today.weekday()]

    with get_conn() as conn:
        state = ensure_weekly_state(conn, ws)
        progress = update_week_progress(conn, ws)
        fd = conn.execute("SELECT * FROM forced_deliverables WHERE week_start=?", (ws,)).fetchone()
        tasks = conn.execute(
            "SELECT id, category, task, est_hours, status, inherited_from FROM tasks WHERE week_start=? ORDER BY id",
            (ws,),
        ).fetchall()

        print_header()
        today_hours = float(input("今天剩余可用时间(小时，如2.5): ").strip() or "2")
        today_energy = int(input("今天精力(1-5): ").strip() or str(state["energy"] or 3))
        today_ddl = input("今天有无硬截止任务(无 / 有+任务id): ").strip() or "无"

        rc = roadmap_context(plan, ws)
        week_item = rc["week"]
        roadmap_block = (
            f"【6周路线图定位】\n"
            f"- 当前周序号: Week {rc['week_idx']}\n"
            f"- 本周主题(P1): {week_item['theme']}\n"
            f"- 本周P1注入: {week_item['p1_note']}\n"
        )

        tasks_text = "\n".join(
            [
                f"- [{t['id']}] {t['category']} | {t['task']} | {t['status']} | {t['est_hours']}h"
                + (f" | inherited_from={t['inherited_from']}" if t["inherited_from"] else "")
                for t in tasks
            ]
        ) or "- (空)"

        avail = {"weekday": state["avail_weekday"] or "?", "weekend": state["avail_weekend"] or "?"}
        fd_p1n = fd["p1_note"] if fd else "(未设置)"
        fd_p1e = fd["p1_exp"] if fd else "(未设置)"
        fd_p3e = fd["p3_exp"] if fd else "(未设置)"
        fd_res = fd["resume"] if fd else "(未设置)"

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
- 可用时段：工作日 {avail.get('weekday','?')} | 周末 {avail.get('weekend','?')}
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
  - P1推导笔记：{fd_p1n}
  - P1实验：{fd_p1e}
  - P3实验闭环：{fd_p3e}
  - 简历：{fd_res}
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

    print("\n" + prompt)


def cmd_done(args: argparse.Namespace) -> None:
    status = args.status
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now_ts(), args.id))
    print(f"✅ 任务[{args.id}] -> {status}")


def cmd_list(args: argparse.Namespace) -> None:
    ws = current_week_start()
    with get_conn() as conn:
        state = ensure_weekly_state(conn, ws)
        tasks = conn.execute(
            "SELECT id, category, task, est_hours, status, inherited_from FROM tasks WHERE week_start=? ORDER BY id",
            (ws,),
        ).fetchall()
    print_header()
    print(f"week_start={ws} | energy={state['energy']} | deadline={state['deadline']}")
    print(f"P1={state['p1_status']} | P2={state['p2_status']} | P3={state['p3_status']} | P4={state['p4_status']}")
    print("任务池:")
    for t in tasks:
        inherited = f" | inherited_from={t['inherited_from']}" if t["inherited_from"] else ""
        print(f"  [{t['id']}] {t['category']} | {t['task']} | {t['status']} | {t['est_hours']}h{inherited}")
    if not tasks:
        print("  (空)")


def cmd_roadmap(args: argparse.Namespace) -> None:
    plan = load_plan()
    ws = current_week_start()
    rc = roadmap_context(plan, ws)
    print(f"{plan['yamlmeta']['title']} (start_week={plan['yamlmeta']['start_week']})")
    for i in range(1, 7):
        wk = plan["weeks"].get(i) or plan["weeks"].get(str(i))
        prefix = "👉" if i == rc["week_idx"] else "  "
        print(f"{prefix} Week {i}: {wk['theme']}")


def cmd_history(args: argparse.Namespace) -> None:
    with get_conn() as conn:
        rows = conn.execute("SELECT week_start, created_at FROM weekly_state ORDER BY week_start DESC").fetchall()
    for r in rows:
        print(f"- {r['week_start']} (created_at={r['created_at']})")


def cmd_export(args: argparse.Namespace) -> None:
    out = BASE_DIR / "tasks.csv"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, week_start, category, task, est_hours, status, inherited_from, created_at, updated_at FROM tasks ORDER BY id"
        ).fetchall()
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "week_start", "category", "task", "est_hours", "status", "inherited_from", "created_at", "updated_at"])
        for r in rows:
            writer.writerow([r[k] for k in r.keys()])
    print(f"✅ 已导出 {out}")


def cmd_import(args: argparse.Namespace) -> None:
    src = BASE_DIR / "tasks.csv"
    if not src.exists():
        raise FileNotFoundError(f"未找到 {src}")
    with src.open("r", encoding="utf-8") as f, get_conn() as conn:
        reader = csv.DictReader(f)
        conn.execute("DELETE FROM tasks")
        for r in reader:
            conn.execute(
                """INSERT INTO tasks(id, week_start, category, task, est_hours, status, inherited_from, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
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

    addp = sub.add_parser("add")
    addp.add_argument("--batch", action="store_true", default=True)

    sub.add_parser("deliverables")
    sub.add_parser("generate")

    donep = sub.add_parser("done")
    donep.add_argument("id", type=int)
    donep.add_argument("status", nargs="?", default="done", choices=["done", "backlog", "dropped"])

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
