# CAN-Space — 开发与协作指南 / Agent Guide

> **用途 Purpose**: 本文档帮助 AI 代理（Claude、Copilot 等）以及所有贡献者理解、构建、测试并参与本项目的开发。它是项目约定、架构决策与开发工作流的唯一权威来源（single source of truth）。
>
> **语言 Language**: 采用中英对照。中文为主说明，英文术语随附以避免歧义，方便中文开发者阅读。

---

## 项目简介 / Project Identity

> **开发溯源 Provenance**：本产品 **CAN-Space** 是基于开源项目 **CAN-Space**（上游 Upstream：
> `https://github.com/Sherin-SEF-AI/CAN-Space`，作者 Sherin Joseph Roy，MIT 许可证）二次开发
> （fork + 个人化改造）。在保留上游全部功能与安全机制的前提下，针对中文支持、界面简化、
> 国产大模型接入与个人化工作流进行改造。因上游为 MIT，派生代码分发时须保留上游版权与
> 许可证文本（见 LICENSE）。详见 [PRD.md](PRD.md) §0。

- **名称 Name**: CAN-Space — CAN 总线逆向工程工作台 / CAN Bus Reverse-Engineering Workbench（基于 CAN-Space 二次开发）
- **语言 Language**: Python 3.11+
- **界面框架 GUI Framework**: PyQt6
- **许可证 License**: MIT（上游同源）
- **代码仓库 Repository**: https://github.com/yjw17694927050-art/CAN（本地目录：`CAN-Space`）
- **状态 Status**: Alpha — 活跃开发中，单人作者项目 / actively developed, single-author project

---

## 架构总览 / Architecture Overview

```
canlab/
├── main.py                 # 程序入口 Entry point：QApplication、安全声明、主窗口
├── mainwindow.py           # 主窗口、工具栏、标签页容器、REST API 生命周期
├── mcp_server.py           # 供外部 AI 工具调用的 MCP 服务器
├── settings_dialog.py      # 设置界面 Settings UI（API Key、缓存、GitHub token）
├── theme.py                # QSS 样式表、字体、颜色 / stylesheet, fonts, colors
│
├── core/                   # 业务逻辑（禁止引入 GUI 依赖 / no GUI imports allowed）
│   ├── state.py            # AppState 单例：帧、信号、DBC、内存上限
│   ├── safety.py           # 全局 ARM TX 安全门 —— 所有发送路径必须调用 require_armed()
│   ├── log_parser.py       # 日志导入 Log import（CSV、candump、PCAN、Vector、MDF）
│   ├── dbc_manager.py      # DBC 加载/保存/校验（基于 cantools）
│   ├── signal_analyzer.py  # 熵、周期性、疑似类型分类 / entropy, periodicity
│   ├── auto_dbc.py         # 从捕获帧自动生成 DBC
│   ├── replay.py           # 日志回放（支持循环、跳转、进度条）
│   ├── injection.py        # 帧注入工作线程
│   ├── fuzzer.py           # 模糊测试工作线程 / fuzzing worker
│   ├── gateway.py          # 两个 CAN 接口之间的 MitM 网关
│   ├── safety_scanner.py   # 安全关键信号扫描（制动、转向、油门）
│   ├── uds.py              # UDS 诊断扫描器 / UDS diagnostic scanner
│   ├── security_access.py  # UDS 安全访问（0x27）seed→key 破解
│   ├── isotp.py            # ISO-TP 会话层 / session layer
│   ├── j1939.py            # J1939 PGN/SPN 解码器
│   ├── obd2_poller.py      # OBD-II Mode 01 PID 轮询
│   ├── xcp.py              # XCP 协议
│   ├── doip.py             # DoIP（基于 IP 的诊断）
│   ├── canfd.py            # CAN FD 辅助工具
│   ├── canid.py            # CAN ID 标准化工具
│   ├── rest_api.py         # 本地 REST API 服务器
│   ├── plugin_loader.py    # 插件系统
│   └── ...                 # （共 40+ 个核心模块）
│
├── tabs/                   # GUI 标签页（每个主要功能一个）
│   ├── frames_tab.py       # 原始帧表格
│   ├── signals_tab.py      # 解码信号表格
│   ├── plot_tab.py         # 时序图
│   ├── ai_engine_tab.py    # AI 信号解读对话
│   ├── dbc_builder_tab.py  # 可视化 DBC 编辑器
│   ├── code_gen_tab.py     # 从 DBC 生成代码
│   ├── intelligence_tab.py # 跨 ID 相关分析、指纹识别
│   ├── injection_tab.py    # 注入、模糊、触发、回放 UI
│   ├── diagnostics_tab.py  # UDS、ISO-TP、J1939、OBD-II UI
│   ├── dashboard_tab.py    # 热力图、时间线、仪表盘
│   ├── auto_re_tab.py      # 自动逆向工程 UI
│   ├── timeline_tab.py     # 事件时间线 + 视频同步
│   ├── obd_dashboard_tab.py# 实时 PID 仪表
│   ├── signal_intelligence_tab.py  # 基于 ML 的信号分类
│   └── gateway_tab.py      # MitM 网关 UI
│
├── panels/                 # 可停靠侧边栏
│   ├── id_panel.py         # ID 列表与过滤器
│   └── inspector_panel.py  # 帧检查器
│
├── ui/                     # 可复用 UI 组件
│   ├── animations.py       # 呼吸灯、数字增长动画
│   └── compute_worker.py   # 后台计算工作线程
│
├── tests/                  # pytest 测试套件
│   ├── test_audit_fixes.py # 已修复 bug 的回归测试
│   ├── test_safety.py      # 安全门测试
│   ├── test_log_importers.py
│   ├── test_rest_api.py
│   └── ...                 # （20+ 个测试文件）
│
├── docs/                   # 文档与截图 / documentation and screenshots
├── sample_data/            # 供测试的示例 CAN 日志
└── examples/               # 插件示例
```

---

## 关键安全规则 / Critical Safety Rules

以下规则**不可妥协**（non-negotiable）。任何违反这些规则的代码都会被拒绝合并。

### 1. ARM TX 安全门 / ARM TX Gate（`core/safety.py`）

**所有**向 CAN 总线发送帧的代码路径，在 `bus.send()` **之前**必须调用 `require_armed()`。

```python
from core.safety import require_armed, BusNotArmedError

# ✅ 正确 Correct——先检查安全门
try:
    require_armed()
except BusNotArmedError:
    self.error.emit("Bus TX is disarmed")
    return
bus.send(msg)

# ❌ 错误 Wrong——绕过了安全门（bypasses the safety gate）
bus.send(msg)
```

**受保护路径 Protected paths**：帧注入（injection）、模糊测试（fuzzer）、日志回放（replay）、网关转发（gateway forwarding）、安全扫描（safety scanner）、UDS 扫描（UDS scan）、REST `/inject` 接口。

### 2. 线程安全 / Thread Safety

- 所有 CAN 总线 I/O 必须运行在 `QThread` 工作线程中，**绝不**在 GUI 主线程执行。
- 每个工作线程必须实现 `stop()` 方法，并遵守 `self._running` 标志（用于优雅停止）。
- 主窗口的 `closeEvent` 通过 `_stop_tab_workers()` 停止所有标签页的工作线程。

### 3. 内存安全 / Memory Safety

- `AppState.max_frames = 500_000` —— 内存中帧数量的硬上限。
- 当超出上限时，`append_frames()` 会丢弃最旧的 chunk（先进先出）。

---

## 开发工作流 / Development Workflow

### 环境搭建 / Setup

```bash
git clone https://github.com/yjw17694927050-art/CAN.git
cd CAN
python3 -m venv .venv
# Windows（本机环境）
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 运行 / Run

```bash
cd canlab
python main.py
```

### 测试 / Test

```bash
# 从仓库根目录执行 From repo root
pytest tests/ -q
```

**预期结果 Expected**：151 passed, 1 skipped（跳过的是 MDF 测试，需要可选的 `asammdf` 依赖）。

### 代码风格 / Code Style

- **`core/` 目录禁止引入 GUI 依赖**。核心模块必须能在headless环境下测试。
- **跨线程通信必须使用信号（Signals）**。工作线程内禁止直接调用 GUI 方法。
- **所有公开 API 需要类型注解（Type hints）**。
- **所有公开函数/类需要文档字符串（Docstrings）**。

---

## 关键设计决策 / Key Design Decisions

| 决策 Decision | 原因 Rationale |
|---------------|----------------|
| 选用 PyQt6 | 全平台原生观感；成熟的 QThread 信号槽线程模型；丰富的表格/图形/树形控件 |
| 选用 cantools 处理 DBC | 行业标准（openpilot、comma.ai 均在使用）；完整支持 DBC 解析/编码/解码/校验；支持 CAN FD |
| ARM TX 安全门模式 | 防止在真实车辆总线上意外发送；统一所有发送路径的控制点；需要用户显式操作（工具栏开关） |
| AppState 分段存储帧数据 | append 成本 O(chunk) 而非 O(n) 全量 concat；仅在读取时才惰性重建完整 DataFrame；内存上限防止长时采集 OOM |

---

## 常见任务指南 / Common Tasks

### 新增一个标签页 / Add a new tab

1. 创建 `tabs/my_tab.py`，继承 `QWidget`
2. 在 `mainwindow.py` 中导入，并添加到 `_add_tabs()`
3. 如果该标签页有后台工作线程，将属性名加入 `_stop_tab_workers()`
4. 在 `tests/test_my_tab.py` 编写测试

### 新增一个核心模块 / Add a new core module

1. 创建 `core/my_module.py`
2. 禁止 GUI 依赖 —— 只能引用 `core.*`、`pandas`、`python-can` 等
3. 若会发送帧，每个 `bus.send()` 前必须调用 `require_armed()`
4. 在 `tests/test_my_module.py` 编写测试

### 新增一种日志格式 / Add a new log format

1. 在 `core/log_parser.py` 添加解析函数
2. 在 `parse_log_file()` 分发器中注册
3. 在 `tests/test_log_importers.py` 添加测试文件

### 新增一个 AI 提供商 / Add a new AI provider

1. 在 `core/ai_client.py` 添加客户端
2. 在 `settings_dialog.py` 添加密钥管理
3. 更新 `AIEngineTab` 以包含新提供商

---

## 已知问题与待办 / Known Issues & TODOs

完整的审计历史见 `docs/AUDIT_FIXES.md`。

### 最新提交已修复（ff2becb）

| Bug 问题 | 文件 File | 修复 Fix |
|----------|-----------|----------|
| 回放循环模式只回放前 8 帧 | `core/replay.py` | 将重名的 `n` 改名为 `dlc_n` |
| 自动 DBC 生成错误的信号 | `core/auto_dbc.py` | 使用真实的 `analyze_id()` 键名 |
| 偶数 access level 时 SecurityAccess 子功能号错误 | `core/security_access.py` | 为 `&` 优先级加括号 |
| 安全扫描器绕过 ARM TX 安全门 | `core/safety_scanner.py` | 添加 `require_armed()` |
| UDS 扫描绕过 ARM TX 安全门 | `core/uds.py` | 添加 `require_armed()` |
| 自定义表达式 eval 可被逃逸 | `core/security_access.py` | 使用 AST 白名单安全编译器 |
| 清缓存可删除任意目录 | `settings_dialog.py` | 添加路径白名单 + 确认框 |
| 关闭窗口时线程未停止导致崩溃 | `mainwindow.py` | 添加 `_stop_tab_workers()` |
| FD 帧被静默解析为空帧 | `core/log_parser.py` | 全文件 FD 检测 |
| 长时采集内存无上限 | `core/state.py` | 添加 `max_frames` 上限 |

### 剩余已知问题 / Remaining known issues

- **UI 线程阻塞**：PLOT 标签页每 50 帧全量重算所有信号（O(N×信号数)）
- **MI 归一化错误**：信号智能模块的 MI 分数用了错误的对数底（系统性低估 30%）
- **校验和检测方向相反**：高熵字节被错误归类为校验和
- **网关队列阻塞**：`q.put()` 无超时可能使 reader 线程卡死
- **无 UI 测试**：标签页、工作线程、GUI 交互的测试覆盖为零

---

## 依赖 / Dependencies

### 必需 / Required

| 包 Package | 用途 Purpose |
|-----------|--------------|
| `python-can` | CAN 接口抽象层 |
| `cantools` | DBC 解析/编码/解码 |
| `pandas` | DataFrame 数据操作 |
| `PyQt6` | GUI 框架 |
| `numpy` | 数值运算 |
| `scipy` | 信号处理（相关分析、熵） |

### 可选 / Optional

| 包 Package | 用途 Purpose | 缺少时的行为 |
|-----------|--------------|--------------|
| `asammdf` | MDF 文件支持 | 跳过 MDF 测试 |
| `anthropic` | Claude AI | AI 功能不可用 |
| `groq` | Groq AI | AI 功能不可用 |
| `ollama` | 本地 AI（无需 API key） | 本地 AI 不可用 |
| `matplotlib` | 绘图 | 图表受限 |
| `pyqtgraph` | 高速绘图 | 图表性能受限 |

---

## 贡献指南 / Contributing

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 为你的改动编写测试
4. 运行 `pytest tests/ -q` —— 所有测试必须通过
5. 用描述性信息提交 commit
6. 推送并创建 Pull Request

### 提交信息格式 / Commit message format

```
<type>: <简短描述 short description>

<可选详细描述 optional longer description>

<可选脚注 optional footer>
```

类型 Types：`feat`（新功能）、`fix`（修复）、`docs`（文档）、`style`（格式）、`refactor`（重构）、`test`（测试）、`chore`（杂务）

---

## 联系方式 / Contact

- **作者 Author**: YJW（yjw17694927050@gmail.com）
- **仓库 Repository**: https://github.com/yjw17694927050-art/CAN