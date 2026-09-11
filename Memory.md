# CAN-Space 项目记忆 / Project Memory

> **用途**：个人开发者的长期记忆文档。每次代码更新或提交后，须同步更新本文档（见「维护约定」）。
> **最近同步时间**：2026-09-11
> **语言**：中文（命令/技术术语保留英文）

---

## 1. 项目概况

**CAN-Space** 是一个 CAN 总线逆向分析桌面工具（PyQt6）。功能覆盖实时采集、日志解析（CSV/BLF/MDF 等）、DBC 解析/生成、信号分析、校验和/计数器识别、帧注入、UDS/DOIP 诊断、J1939、OBD2、网关、回放等。

- 入口：`canlab/main.py`
- 构建规格：`canlab.spec`（PyInstaller）
- 启动脚本：`启动CAN-Space.bat`
- 运行依赖：`requirements.txt`

## 2. 技术栈

- 语言：Python 3（venv：`.venv`）
- GUI：PyQt6 + pyqtgraph（绘图）
- 数据处理：pandas / numpy
- 测试：pytest + pytest-qt
- CAN 工具库：cantools 等（见 requirements.txt）
- 构建：PyInstaller

## 3. 目录结构

```
CAN-Space/
├── AGENT.md                  # AGENT 开发指导（双语）
├── SPEC.md                   # 技术规格说明
├── 个人开发规范.md             # 个人化工程约定
├── CAN-Space个人化改造清单.docx   # 改造清单（一次性交付物）
├── README.md / LICENSE
├── launch: 启动CAN-Space.bat
├── canlab/
│   ├── main.py               # 入口
│   ├── mainwindow.py         # 主窗口，_stop_tab_workers() 关窗回收线程
│   ├── settings_dialog.py    # 设置；缓存清理限 ~/.canlab 子目录+需确认
│   ├── theme.py              # 配色主题 COLORS
│   ├── core/                 # 核心逻辑（严禁 GUI 依赖，headless 可测）
│   │   ├── state.py          # AppState 单例；max_frames=500_000 防 OOM
│   │   ├── safety.py         # ARM 发射安全门 require_armed()
│   │   ├── security_access.py# 安全访问；seed→key 用 ast 白名单解析(禁 eval)
│   │   ├── log_parser.py     # 日志解析（全文件扫 FD 帧）
│   │   ├── signal_analyzer.py# 信号分析；MI 归一化用 ln(16)
│   │   ├── counter_checksum_detector.py # 校验和/计数器检测（按算法去重）
│   │   ├── gateway.py        # 网关队列，put(timeout=0.05) 防死锁
│   │   ├── replay.py / injection.py / uds.py / doip.py / isotp.py
│   │   ├── j1939.py / obd2_pids.py / obd2_poller.py
│   │   ├── fuzzer.py / trigger.py / test_sequence.py
│   │   └── ...（60+ 核心模块）
│   ├── tabs/                 # 各功能标签页（15 个）
│   │   ├── frames_tab.py     # 帧表；300ms 合并刷新；follow/freeze
│   │   ├── plot_tab.py       # 绘图；150ms 节流；共享 DataFrame 视图
│   │   ├── signals_tab.py    # 信号分析；事件用绑定方法连接
│   │   └── ... 
│   ├── ui/ / panels/ / examples/ / sample_data/sample_kona_drive.csv
│   └── mcp_server.py
└── tests/                    # 22 个测试文件
    ├── conftest.py
    ├── test_gui_tabs.py      # pytest-qt，参数化覆盖 15 标签页+交互（18 用例）
    └── test_*.py             # 核心/安全/日志/REST/UDS 等
```

## 4. 核心架构约定（硬性约束）

改动时勿破坏，详见 `个人开发规范.md` 与 `AGENT.md`：

- **ARM 安全门**：所有总线写帧路径（injection/replay/gateway/uds/rest_api）在 `bus.send()` 前必须 `require_armed()`。
- **表达式沙箱**：用户可控表达式只走 ast 白名单，禁止 `eval()`。
- **内存上限**：`state.py` 的 `max_frames`（500_000）勿随意移除。
- **线程归属**：QThread 实例存 self，防 GC 提前销毁。
- **信号连接**：连接全局单例信号用绑定方法，不用 lambda（lambda 无法自动断开）。
- **ID 统一**：CAN ID 经 `core.canid.normalize_id`（大写、去 0x、≥3 位十六进制）。
- **core/ 禁 GUI 依赖**：核心模块 headless 可测。
- **提交门槛**：提交前 `pytest tests/ -q` 全量全绿。

## 5. Git 信息

- 远端：`origin = https://github.com/yjw17694927050-art/CAN-Space.git`（仓库已由 CAN 更名）
- 提交身份：`YJW <yjw17694927050@gmail.com>`
- 提交规范：语义化前缀（`fix:`/`feat:`/`test:`/`docs:`/`refactor:`）
- 追加提交用 `--force-with-lease`（勿用裸 `--force` 覆写他人）。

## 6. 测试状态

- 全套纳入范围：22 个测试文件
- UI：`tests/test_gui_tabs.py`，**18 个用例**
- 全量结果：**169 passed, 1 skipped**（跳过项为 UDS 硬件依赖），本次为历史实测，提交前应复核重跑。
- 运行：`pytest tests/ -q`（Windows 用 `.venv\Scripts\python.exe`）

## 7. 近期变更记录 / Changelog

> 每次代码更新/提交后追加记录，保持「日期 · 提交 hash · 摘要」。

- **2026-09-11 · `2d432af`** refactor：项目品牌统一为 CAN-Space，更新远端仓库地址
- **2026-09-11 · `c899e4a`** docs：维护约定补充禁止 amend 写 hash 的规则
- **2026-09-11 · `882364b`** docs：新增本项目记忆文档 Memory.md（架构约定、测试状态、变更记录、维护约定）
- **2026-09-10 · `2ebf799`** docs：新增个人开发规范与改造清单，更新 SPEC 测试章节
- **2026-09-10 · `61b7b56`** test：新增 pytest-qt 标签页界面测试（test_gui_tabs.py）
- **2026-09-10 · `1b1147e`** fix：修复核心分析缺陷与界面卡顿
  - MI 归一化改用 ln(16)（原 log2(16) 低估 ~30%）
  - 网关队列 put 加 timeout=0.05 防死锁
  - 校验和按算法去重，消除 XOR 帧整帧误报
  - PLOT 标签页 150ms 节流 + 共享 DataFrame 视图
  - signals 事件改绑定方法连接防泄漏
- **2026-09-10 · `7d4463f`** docs：AGENT.md / SPEC.md 双语化
- **2026-09-10 · `ff2becb`** fix：修复第 1~3 批 10 项功能/安全/稳定缺陷

## 8. 待办与遗留

- **临时探针未提交**：`_probe.py`、`_verify_checksum.py`、`_verify_mi.py`（调试脚本，可删除）。
- **疑似遗留文件**：根目录出现 `Read` 文件，来源待确认（非本项目生成）。
- **全量测试复核**：`169 passed` 为历史结果，近期有代码改动，提交前需重跑确认。
- **后续版本规划**：见 `SPEC.md` 第 13 节路线图。

---

## 附：维护约定（本文件如何同步）

1. 每次**代码更新**（功能/修复/重构）完成后，在「近期变更记录」追加一行：日期 · hash · 摘要；若涉及目录或约定硬性变化，更新第 3/4 节。
2. 每次**提交并推送**后，在「近期变更记录」追加一行（日期 · hash · 摘要），并同步更新第 5/6 节；**记录本次提交的 hash 用普通追加提交实现，不要用 `git commit --amend`**——amend 会重新计算 hash，导致已写入的 hash 引用永久对不上（已踩坑）。commit 后再修正记录，也应新提交而非 amend。
3. 若测试全量数字变化，更新第 6 节，注明实测日期。
4. 待办变化随时更新第 8 节，解决即勾选移除。

*文档结束 End of memory*