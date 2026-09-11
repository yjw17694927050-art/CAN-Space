# CAN-Space — 技术规格说明书 / Technical Specification

> **版本 Version**：1.0（Alpha）
> **日期 Date**：2026-09-10
> **状态 Status**：活跃开发中 / Active development
>
> **开发溯源 Provenance**：本产品 **CAN-Space** 基于开源 **CAN-Space**
> （`https://github.com/Sherin-SEF-AI/CAN-Space`，Sherin Joseph Roy，MIT）二次开发。
> 详见 [PRD.md](PRD.md) §0。
>
> **语言 Language**：中英对照。中文为主，技术术语保留英文，方便中文开发者理解。

---

## 1. 总览 / Overview

CAN-Space 是一个用于 CAN 总线数据逆向工程的桌面应用程序（基于 CAN-Space 二次开发）。它提供了采集（capture）、分析（analysis）、解码（decode）、以及在隔离台架（isolated bench setup）上注入（inject）CAN 帧的工具。应用程序基于 Python 3.11+ 与 PyQt6 构建。

### 1.1 目标 / Goals

- 提供统一的 CAN 总线逆向工程工作站
- 通过 python-can 支持多种 CAN 接口
- 自动化信号发现与 DBC 生成
- 集成 AI 辅助信号解读
- 在分析（analysis）与发送（transmission）之间保持严格的安全边界

### 1.2 非目标 / Non-Goals

- 实时 ECU 刷写或标定（real-time ECU flashing/calibration）
- 车型特定调参（vehicle-specific tuning —— 请使用专用工具）
- 生产级汽车诊断（production-grade diagnostics —— 请使用 OEM 工具）

---

## 2. 系统架构 / System Architecture

### 2.1 高层架构 / High-Level Architecture

```
┌─────────────────────────────────────────┐
│           PyQt6 GUI 层 GUI Layer        │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────────┐  │
│  │标签页│ │面板 │ │面板 │ │设置对话框│  │
│  │ Tabs│ │ ID  │ │Insp.│ │ Settings│  │
│  │(15) │ │     │ │     │ │ Dialog  │  │
│  └──┬──┘ └──┬──┘ └──┬──┘ └────┬────┘  │
│     └────────┴────────┴────────┘       │
│              MainWindow 主窗口         │
│            （QMainWindow）             │
└─────────────────┬───────────────────────┘
                  │ 信号/槽 signals/slots
┌─────────────────▼───────────────────────┐
│      AppState（单例 Singleton）        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │帧Frames │ │信号上    │ │DBC管理  │  │
│  │DataFrame│ │列表 list │ │manager  │  │
│  └─────────┘ └─────────┘ └─────────┘  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│        核心引擎层 Core Engine Layer    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │分析      │ │协议      │ │安全门   │  │
│  │Analysis │ │Protocol │ │Safety   │  │
│  │(40+模块) │ │(UDS/    │ │ Gate    │  │
│  │         │ │ J1939)  │ │         │  │
│  └─────────┘ └─────────┘ └─────────┘  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│     硬件抽象层 Hardware Abstraction    │
│      python-can（BusABC）              │
│    ┌────────┐ ┌────────┐ ┌────────┐   │
│    │Socket  │ │ PCAN   │ │ Vector │   │
│    │ CAN    │ │        │ │        │   │
│    └────────┘ └────────┘ └────────┘   │
└─────────────────────────────────────────┘
```

### 2.2 线程模型 / Threading Model

| 线程 Thread | 用途 Purpose | 生命周期 Lifetime |
|-------------|--------------|-------------------|
| 主线程 / Main (GUI) | 事件循环、渲染、用户输入 | 应用生命周期 |
| LiveCANWorker | 实时 CAN 帧采集 | 输入法（live）模式激活期间 |
| MultiBusWorker | 多接口采集 | 多总线激活期间 |
| ReplayWorker | 日志文件回放 | 回放期间 |
| InjectionWorker | 帧注入 | 注入期间 |
| FuzzerWorker | 模糊测试 | 模糊期间 |
| GatewayWorker | MitM 转发 | 网关激活期间 |
| SafetyScanWorker | 安全关键扫描 | 扫描期间 |
| UDSScanWorker | 诊断扫描 | 扫描期间 |
| SecurityAccessWorker | seed/key 破解 | 破解期间 |
| REST API 线程 | 本地 HTTP 服务器 | API 启用期间 |
| ComputeWorker | 后台分析 | 按需 |

**规则 Rule**：所有工作线程必须实现 `stop()` 并遵守 `self._running`。主窗口的 `closeEvent` 调用 `_stop_tab_workers()` 在退出前 join 所有线程。

---

## 3. 数据模型 / Data Model

### 3.1 帧存储 / Frame Storage（`core/state.py`）

```python
class AppState(QObject):
    # 信号 Signals
    frames_updated = pyqtSignal()
    id_selected = pyqtSignal(str)
    dbc_updated = pyqtSignal()
    # ... 20+ 个信号

    # 存储 Storage
    _frames_base: pd.DataFrame       # 历史帧（来自文件）
    _frame_chunks: list[pd.DataFrame]  # 实时 chunk（追加）
    _frames_cache: pd.DataFrame      # 惰性拼接缓存（lazy concatenation cache）
    max_frames: int = 500_000        # 内存上限
```

**帧 DataFrame 结构 / Frame DataFrame schema**：

| 列 Column | 类型 Type | 说明 Description |
|-----------|-----------|------------------|
| `Timestamp` | float | 自 epoch 起的秒数 |
| `ID` | str | 十六进制 CAN ID（如 "0x123"） |
| `DLC` | int | 数据长度码（0-8） |
| `B0`-`B7` | int | 数据字节 |
| `Extended` | bool | 29 位 ID 标志 |
| `Bus` | str | 接口名（多总线） |
| `Direction` | str | "RX"（接收）或 "TX"（发送） |

### 3.2 信号定义 / Signal Definition

```python
signal_def = {
    "message_id":   "0x123",       # 消息 ID
    "message_name": "WHL_SPD",     # 消息名（如"轮速"）
    "signal_name":  "WHL_SPD_FL",  # 信号名
    "start_bit":    0,             # 起始位
    "length":       16,            # 位长
    "byte_order":   "little",      # 字序："big" 或 "little"
    "value_type":   "unsigned",    # 类型："signed" 或 "unsigned"
    "scale":        0.03125,       # 缩放系数
    "offset":       0.0,           # 偏移量
    "minimum":      0.0,           # 最小物理值
    "maximum":      255.996875,    # 最大物理值
    "unit":         "km/h",        # 单位
}
```

### 3.3 DBC 管理 / DBC Management

- 使用 `cantools` 进行 DBC 解析、编码、解码
- 支持导入：DBC、ARXML、CAN matrix
- 支持导出：DBC、openpilot DBC、CANdb++、ARXML、Wireshark Lua

---

## 4. 安全架构 / Safety Architecture

### 4.1 ARM TX 安全门 / ARM TX Gate（`core/safety.py`）

```python
_armed = False  # 全局状态，默认不布防 / disarmed by default

def require_armed() -> None:
    """除非 TX 已显式布防，否则抛出 BusNotArmedError。"""
    if not is_armed():
        raise BusNotArmedError("Bus transmit is disarmed...")
```

**受保护路径 Protected paths**（每个 `bus.send()` 之前必须调用 `require_armed()`）：

| 模块 Module | 方法 Method | 用途 Purpose |
|-------------|-------------|--------------|
| `injection.py` | `InjectionWorker.run()` | 信号注入 |
| `fuzzer.py` | `FuzzerWorker.run()` | 模糊测试 |
| `replay.py` | `ReplayWorker.run()` | 日志回放 |
| `gateway.py` | `GatewayWorker.run()` | MitM 转发 |
| `safety_scanner.py` | `SafetyScanWorker.run()` | 安全扫描 |
| `uds.py` | `UDSScanner._send_to()` | UDS 请求 |
| `uds.py` | `UDSScanner._send_and_recv()` | UDS 请求 |
| `rest_api.py` | `/inject` 接口 | REST 注入 |

### 4.2 安全特性 / Safety Features

- **首次启动免责声明**：不确认风险无法继续
- **ARM TX 开关**：工具栏按钮，默认关闭，需用户显式点击开启
- **只读 UDS 扫描**：破坏性服务需单独勾选 + 确认
- **路径白名单**：清缓存仅允许在 `~/.canlab` 目录内
- **表达式沙箱**：自定义 seed→key 表达式通过 AST 白名单校验

---

## 5. 协议支持 / Protocol Support

### 5.1 CAN / CAN FD

- 经典 CAN：11 位与 29 位 ID，最多 8 字节
- CAN FD：最多 64 字节，支持 BRS（比特率切换）
- 日志格式：CSV、candump、PCAN、Vector ASC、MDF（可选）

### 5.2 UDS（ISO 14229）

| 服务 Service | ID | 支持 |
|--------------|-----|------|
| DiagnosticSessionControl（诊断会话控制） | 0x10 | ✅ |
| ECUReset（ECU 复位） | 0x11 | ✅ |
| SecurityAccess（安全访问） | 0x27 | ✅ |
| ReadDataByIdentifier（按 ID 读数据） | 0x22 | ✅ |
| WriteDataByIdentifier（按 ID 写数据） | 0x2E | ✅ |
| RoutineControl（例程控制） | 0x31 | ✅ |
| RequestDownload（请求下载） | 0x34 | ✅ |
| TransferData（传输数据） | 0x36 | ✅ |
| RequestTransferExit（结束传输） | 0x37 | ✅ |

### 5.3 J1939

- PGN/SPN 解码
- DM1（当前激活 DTC 诊断故障码）
- DM2（历史 DTC）

### 5.4 OBD-II（ISO 15031）

- Mode 01：实时数据（PID 轮询）
- Mode 03：已存储 DTC
- Mode 04：清除 DTC
- Mode 09：车辆信息

### 5.5 ISO-TP（ISO 15765-2）

- 单帧 / Single frame（SF）
- 首帧 / First frame（FF）
- 连续帧 / Consecutive frame（CF）
- 流控 / Flow control（FC）

### 5.6 XCP（通用测量与标定协议）

- 基础 XCP 命令
- DAQ 列表配置

### 5.7 DoIP（ISO 13400）

- 基于 IP 的诊断
- 车辆发现 / Vehicle discovery
- 路由激活 / Routing activation

---

## 6. AI 集成 / AI Integration

### 6.1 提供商 / Providers

| 提供商 Provider | 模型 Model | API Key | 本地 Local |
|-----------------|-----------|---------|-----------|
| Anthropic | Claude 3.5 Sonnet | 必需 Required | 否 No |
| Groq | Llama 3.1 70B | 必需 Required | 否 No |
| Ollama | 任意本地模型 | 不需要 Not required | 是 Yes |

### 6.2 AI 引擎标签页 / AI Engine Tab

- 发送 CAN ID + 采集帧给 AI 进行解读
- 将离线 ML 分析结果（熵、周期、相关性）注入提示词 / prompt
- 跨会话持久化对话记忆（persistent conversation memory）
- 支持 Markdown 渲染响应

### 6.3 MCP 服务器 / MCP Server

- 供外部 AI 工具调用的 Model Context Protocol 服务器
- 暴露 CAN-Space 状态与分析结果
- 在 localhost 运行，需显式启用

---

## 7. 插件系统 / Plugin System

### 7.1 插件 API / Plugin API

```python
# examples/plugins/hello_plugin.py
def register(api):
    """插件加载时被调用 Called when plugin is loaded."""
    api.add_menu_action("Hello", on_hello)   # 添加菜单项
    api.add_frame_handler(on_frame)          # 可选：每帧回调

def on_hello(api):
    api.show_message("Hello from plugin!")

def on_frame(api, frame):
    pass  # 处理每一帧 Process each frame
```

### 7.2 插件发现 / Plugin Discovery

- 启动时扫描 `plugins/` 目录
- 加载定义了 `register()` 函数的 `.py` 文件
- 插件在主线程运行，可访问 AppState

---

## 8. REST API

### 8.1 端点 / Endpoints

| 方法 Method | 路径 Path | 说明 Description |
|-------------|-----------|------------------|
| GET | `/status` | 服务器状态、帧计数、布防状态 |
| GET | `/frames` | 最近帧（分页） |
| GET | `/frames/{id}` | 指定 CAN ID 的帧 |
| POST | `/inject` | 注入帧（需 ARM TX + token） |
| GET | `/signals` | 当前信号值 |
| GET | `/dbc` | 当前 DBC（JSON） |

### 8.2 认证 / Authentication

- `Authorization` 头中的 Bearer token
- 首次启用 API 时生成
- 存储在系统钥匙串（system keyring）

---

## 9. 测试 / Testing

### 9.1 测试结构 / Test Structure

```
tests/
├── conftest.py              # 夹具 Fixtures（mock bus、示例帧）
├── test_gui_tabs.py         # pytest-qt 界面测试（15 个标签页构建 + 关键交互）
├── test_audit_fixes.py      # 已修复 bug 的回归测试
├── test_safety.py           # 安全门测试
├── test_log_importers.py    # 日志格式测试
├── test_rest_api.py         # API 端点测试
├── test_uds_safety.py       # UDS 安全测试
└── ...                      # 20+ 个测试文件
```

> **界面测试说明 / UI Test Note**：UI 用例采用 **pytest-qt**，按标签页逐个构建并驱动实际控件交互（参数化覆盖全部 15 个标签页），避免整窗 MainWindow 在 Windows 拆解时的原生崩溃。被测代码与 App 一致地通过顶层 `core.*` 导入，避免与 `canlab.core.*` 形成双模块单例、界面读到空数据。

### 9.2 测试覆盖 / Test Coverage

| 类别 Category | 文件数 Files | 覆盖 Coverage |
|---------------|-------------|---------------|
| 核心逻辑 Core logic | 15 | 良好 Good |
| 安全 Safety | 2 | 良好 Good |
| 日志格式 Log formats | 1 | 良好 Good |
| REST API | 1 | 基础 Basic |
| UI（界面，pytest-qt） | 1 | 良好 Good（18 个用例） |

### 9.3 运行测试 / Running Tests

```bash
pytest tests/ -q                    # 全部测试 All tests（Windows 下用 .venv\Scripts\python.exe）
pytest tests/test_safety.py -v      # 指定文件 Specific file
pytest -k "test_arm" -v             # 模式匹配 Pattern match
pytest tests/test_gui_tabs.py -v    # 界面测试 UI tests（需 pytest-qt、Qt 显示环境）
```

**预期结果 Expected**：169 passed, 1 skipped（跳过项为 UDS 硬件依赖测试）。提交代码前应保持全量全绿（见个人开发规范第 1 节）。

---

## 10. 构建与分发 / Build & Distribution

### 10.1 PyInstaller

```bash
# 构建独立可执行文件 Build standalone executable
pyinstaller canlab.spec

# 输出到 dist/CAN-Space/
```

### 10.2 PyInstaller 规格 / PyInstaller Spec（`canlab.spec`）

- 单文件或单目录模式
- 打包 Qt 插件、cantools、pandas
- 图标：`canlab/canlab.png`
- 内嵌版本信息 / Version info embedded

---

## 11. 性能目标 / Performance Targets

| 指标 Metric | 目标 Target | 当前 Current |
|-------------|-------------|--------------|
| 帧采集速率 Frame capture rate | 10,000 fps | ~5,000 fps |
| 内存（100 万帧）Memory (1M frames) | < 500 MB | ~400 MB |
| 启动时间 Startup time | < 3 s | ~2 s |
| 绘图刷新（10 信号）Plot refresh | 60 fps | ~30 fps |
| 日志加载（100 万帧）Log file load | < 10 s | ~5 s |

---

## 12. 安全考量 / Security Considerations

### 12.1 威胁模型 / Threat Model

| 威胁 Threat | 缓解措施 Mitigation |
|-------------|---------------------|
| 在真实总线上意外注入 | ARM TX 安全门，默认关闭 |
| 恶意日志文件攻击 | 输入校验，无代码执行 |
| API token 窃取 | 系统钥匙串存储 |
| 表达式注入 | AST 白名单，无 `__builtins__` |
| 清缓存路径穿越 | 白名单限制到 `~/.canlab` |

### 12.2 数据隐私 / Data Privacy

- 无遥测与分析上报
- API key 存储在系统钥匙串（非明文）
- 对话历史本地存储（`~/.canlab/`）
- 未经用户显式操作不进行云同步

---

## 13. 未来路线图 / Future Roadmap

### 短期（下一版本）/ Short-term

- [ ] 使用 pytest-qt 增加 UI 测试覆盖
- [ ] 修复剩余 MI 归一化 bug
- [ ] 修复校验和检测方向
- [ ] 网关队列超时处理
- [ ] 绘图标签页性能优化

### 中期 / Medium-term

- [ ] 全标签页 CAN FD 支持
- [ ] 以太网/DoIP 采集
- [ ] 云端 DBC 共享（可选加入）
- [ ] 协作分析会话

### 长期 / Long-term

- [ ] 基于 Web 的版本（Pyodide/WebAssembly）
- [ ] 移动端配套应用
- [ ] 硬件在环（HIL）集成

---

## 附录 / Appendix

### 文件格式支持矩阵 / File Format Support Matrix

| 格式 Format | 导入 Import | 导出 Export | 备注 Notes |
|-------------|------------|------------|-----------|
| DBC | ✅ | ✅ | 主要格式 Primary format |
| ARXML | ✅ | ✅ | 导出为实验性 |
| CAN matrix | ✅ | ❌ | 类似 CSV 的格式 |
| CANdb++ | ❌ | ✅ | 仅导出 |
| openpilot DBC | ❌ | ✅ | 仅导出 |
| Wireshark Lua | ❌ | ✅ | 仅导出 |
| CSV | ✅ | ✅ | 通用帧日志 |
| candump | ✅ | ✅ | Linux can-utils |
| PCAN | ✅ | ❌ | PEAK-System |
| Vector ASC | ✅ | ❌ | Vector 工具 |
| MDF | ✅ | ❌ | 需要 `asammdf` |

### CAN 接口支持 / CAN Interface Support

| 接口 Interface | Windows | Linux | macOS |
|----------------|---------|-------|-------|
| SocketCAN | ❌ | ✅ | ❌ |
| PCAN | ✅ | ✅ | ❌ |
| Vector | ✅ | ❌ | ❌ |
| Kvaser | ✅ | ✅ | ❌ |
| SLCAN | ✅ | ✅ | ✅ |
| Virtual（虚拟） | ✅ | ✅ | ✅ |

### 快捷键 / Keyboard Shortcuts

| 快捷键 Shortcut | 操作 Action |
|-----------------|-------------|
| Ctrl+O | 打开日志文件 Open log file |
| Ctrl+S | 保存 DBC Save DBC |
| Ctrl+Q | 退出 Quit |
| F5 | 刷新帧 Refresh frames |
| Ctrl+F | 查找 ID Find ID |
| Space 空格 | 冻结/跟随 Freeze/follow |

---

*规格文档结束 / End of specification*