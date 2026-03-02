# Planner 使用说明

## 文件结构

```text
planner/
  planner.py      # 主脚本
  plan.yaml       # 6周路线图（手动可改）
  planner.db      # SQLite记忆库（自动生成）
  tasks.csv       # export/import 中间文件（自动生成）
```

## 快速开始

```bash
python planner/planner.py --help
```

## 命令清单

- `init`：录入本周状态（精力/deadline/P1-P4进度/可用时段），每周一次
- `rollover`：复制上周 `todo/backlog` 到本周，并写入 `inherited_from`
- `add --batch`：先展示本周 roadmap，再逐条加入任务池，最后可补充自由任务
- `deliverables`：设置 4 项强制交付物
- `generate`：生成两段 prompt（本周计划 + 今日排序）
- `done <id> [done|backlog|dropped]`：更新任务状态
- `list`：查看本周状态与任务池
- `roadmap`：查看 6 周路线图与当前定位
- `history`：查看历史周
- `export`：导出 `tasks.csv`
- `import`：从 `tasks.csv` 导回

## 周一标准流程

1. `init`（只录状态）
2. `rollover`（继承上周未完成）
3. `add --batch`（补齐本周任务池）
4. `deliverables`（固定四项交付）
5. `list` + `roadmap`（检查）

## 每天流程

1. `generate`，回答 3 个问题：
   - 今天剩余可用时间
   - 今天精力（1-5）
   - 今天有无硬截止（无 / 有+任务id）
2. 按 prompt 执行
3. 随时 `done <id>` 回写状态

## 数据说明

- SQLite 表：`weekly_state`、`tasks`、`forced_deliverables`、`week_progress`、`prompt_log`
- `week_progress` 由 `tasks` 自动推断
- `rollover` 为“纯复制”，不会改动原周任务
- 重复执行 `rollover` 时，如果本周已有继承任务会告警并跳过

## 备注

- 所有交互顶部会显示类别说明：`H0 / P1 / P2 / P3 / P4`
- `plan.yaml` 可按你的节奏手动编辑
