# Planner 使用说明（完整）

## 1) 文件结构

```text
planner/
  planner.py      # 主脚本
  plan.yaml       # 6周路线图 + 默认交付物模板（手动可改）
  planner.db      # SQLite记忆库（自动生成）
  tasks.csv       # export/import 中间文件（自动生成）
```

## 2) 设计原则（你关心的点）

- `init` 只管“周状态”，不录任务。
- `add --batch` 只管“任务池”。
- `generate` 输出**一版 Prompt**，内部含两段：
  - 段一：本周计划
  - 段二：今日排序
- 交付物默认从 `plan.yaml` 预置：
  - 非 H0：`deliverables --edit` 可改
  - H0：用 `refresh-h0` 在线刷新（高频）

## 3) 命令详解

### `python planner/planner.py init`
每周一次，录入：
- 本周精力（1-5）
- 工作 deadline/阻塞
- P1~P4 当前进度
- 工作日/周末可用时段
- 备注

### `python planner/planner.py rollover`
每周一次，把上周 `todo/backlog` 复制到本周，写 `inherited_from`。
- 纯复制，不改动上周原任务
- 如果本周已继承过，重复执行会告警并跳过

### `python planner/planner.py add --batch`
每周一次，批量加入任务池：
1. 先展示本周 roadmap
2. 逐条问 `y/n`（输入非 y/n 会要求重输）
3. 已选任务**自动估算时长**（不用你再填）
4. 最后支持补充自由任务（自由任务仍可手输时长）

### `python planner/planner.py deliverables --show`
查看本周四项交付物 + H0 交付条目。

### `python planner/planner.py deliverables --edit`
可选地修改非 H0 的交付物（P1笔记/P1实验/P3闭环/简历）。

### `python planner/planner.py refresh-h0`
在线刷新 H0 工作交付/阻塞（推荐高频使用）。

### `python planner/planner.py generate`
每天使用。会询问：
- 今天下班时间（HH:MM）
- 今日精力
- 今日硬截止

今日剩余时间自动计算：
- `下班时间 - 当前时间`
- 再扣除与区间重叠的午休 `12:00-14:00`
- 再扣除与区间重叠的晚餐 `18:00-19:00`

### `python planner/planner.py done <id> [done|backlog|dropped]`
更新任务状态，默认 `done`。

### `python planner/planner.py list`
查看本周状态、任务池、交付物。

### `python planner/planner.py roadmap`
查看 6 周路线图及当前所在周。

### `python planner/planner.py history`
查看历史周列表。

### `python planner/planner.py export`
导出 `tasks.csv`（Excel 可编辑）。

### `python planner/planner.py import`
从 `tasks.csv` 导回任务。

## 4) 标准流程

### 每周一流程
1. `init`
2. `rollover`
3. `add --batch`
4. `deliverables --show`（必要时 `--edit`）
5. `list` + `roadmap`

### 每天流程
1. `refresh-h0`（有变动就刷新）
2. `generate`
3. 执行后 `done <id>` 回写

## 5) 数据表说明

- `weekly_state`: 周状态
- `tasks`: 任务池（含 `inherited_from`）
- `forced_deliverables`: 交付物
- `week_progress`: 自动推断完成度
- `prompt_log`: 历史 prompt
