# Planner 使用说明（完整）

## 文件结构

```text
planner/
  planner.py      # 主脚本
  plan.yaml       # 6周路线图 + 每项任务预置时长(est_h) + 默认交付物
  planner.db      # SQLite记忆库（自动生成）
  tasks.csv       # export/import 中间文件（自动生成）
```

## 关键规则（本次更新）

1. `deadline/阻塞` 支持多行输入（空行结束）。
2. P1/P2/P3/P4 进度不输入时默认 `0`。
3. 工作日可用时段不输入时默认 `9:30-21:30`。
4. 任务时长不再由代码估算，改为读取 `plan.yaml` 中每个任务的 `est_h`。
5. `generate` 输出是**一个 prompt**，内部有两段：段一周计划 + 段二今日排序。

## 命令详解

### `python planner/planner.py init`
- 每周一次，仅录周状态。
- `工作deadline/阻塞` 支持多行；直接回车结束。
- 若本周已存在交付物记录，会同步把 H0 交付刷新为最新 deadline。

### `python planner/planner.py add --batch`
- 展示本周 roadmap 项。
- 每项输入 `y/n`（非 `y/n` 会要求重输）。
- 加入后时长直接使用 `plan.yaml` 对应 `est_h`。

### `python planner/planner.py deliverables --show`
查看本周交付物。

### `python planner/planner.py deliverables --edit`
仅修改非 H0 交付物。

### `python planner/planner.py refresh-h0`
在线刷新 H0（支持多行）。

### `python planner/planner.py generate`
- 输入今日精力 + 今日硬截止。
- 自动计算今日剩余可用时间：
  - 工作窗口固定为 `9:30-21:30`
  - 从当前时刻开始计算到 21:30
  - 减去与 `12:00-14:00` 重叠的时长
  - 减去与 `18:00-19:00` 重叠的时长
- 输出一个双段结构 prompt，并写入 `prompt_log`。

### 其他
- `rollover`：复制上周 `todo/backlog` 到本周并记录 `inherited_from`
- `done <id> [done|backlog|dropped]`：更新状态
- `list`：查看本周状态+任务+交付物
- `roadmap`：查看6周总览
- `history`：历史周
- `export/import`：CSV 往返
