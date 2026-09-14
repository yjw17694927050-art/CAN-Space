# CAN-Space

CAN-Space 是一个面向汽车 CAN 总线分析、诊断和逆向工程的 PyQt6 桌面工作站。

本项目基于开源项目 [CANlab](https://github.com/Sherin-SEF-AI/CANlab)（MIT 许可证）二次开发。我们保留并扩展了原项目的分析工作台，同时加入中文界面、车辆诊断、人工智能/机器学习辅助能力，以及更严格的总线安全、并发和线程生命周期控制。当前版本适合实验室、台架和离线日志分析，仍属于 Alpha（内测）阶段。

## 我们在这个开源项目上做了什么

### 1. CAN 总线访问安全与并发控制

- 增加统一的 `CanCoordinator`，集中管理物理总线、接收线程、订阅分发和停止顺序。
- 同一物理总线只保留一个接收线程，避免多个线程同时 `recv()` 造成竞争。
- 通过 `SafeBusAdapter` 统一发送入口；发送默认关闭，必须显式启用 ARM。
- 图形界面、REST 接口、脚本和诊断发送都经过同一安全门控，不允许旁路发帧。
- 同一诊断通道上的请求/响应使用事务锁，避免并发请求串包。
- 双通道网关分别维护各自的物理总线和接收线程。

### 2. 图形界面与后台线程生命周期

- 注入和 DTC 扫描改为后台 worker，图形界面线程只负责界面和信号槽。
- DTC 清除只接受 UDS `0x54` 正响应，拒绝把其他正响应误判为成功。
- 可停止等待和周期任务都使用可唤醒机制，关闭窗口时不会长时间卡住。
- 每个标签页负责停止自己创建的 worker；应用退出时按依赖顺序关闭 worker、接收线程和物理总线。

### 3. 日志帧数硬上限

- 对文件导入、文本导入、批量回放、分析和绘图入口统一执行 `max_frames` 限制。
- 超过上限时保留最新的 N 帧，并报告截断状态。
- 使用惰性分块读取和有界缓存，避免大日志一次性加载到内存。
- `max_frames <= 0` 视为无效配置并抛出 `ValueError`。
- 时间戳来源和回放截断信息会保留在结果元数据中。

### 4. GitHub 内容与身份校验

- GitHub 读取范围显式限定为分支（branch）、目录树（tree）或文件（blob），避免把任意 API 路径当成文件。
- 对仓库、分支、路径和 SHA 做安全解析与身份校验。
- 处理非 UTF-8 内容、文件大小上限、原子写入和 SHA-256 校验，避免部分下载覆盖本地文件。

### 5. 分析、诊断和工程化能力

- 支持 UDS、ISO-TP、OBD-II、J1939、XCP 和 DoIP 等常见协议的分析辅助。
- 提供离线字段识别、信号聚类、异常检测、DBC/ARXML/CAN Matrix 导入导出和代码生成。
- 支持人工智能上下文构建、机器学习辅助分析以及可选视觉参考能力。
- 增加 REST 接口和 MCP 服务，便于自动化测试与外部工具集成。

## 架构概览

```text
PyQt6 图形界面 / 功能页
    │ 信号/槽；不直接执行 CAN 输入输出
    ▼
AppState + CanCoordinator
    ├─ 唯一物理总线所有者
    ├─ 唯一接收线程
    ├─ ARM 安全发送入口
    ├─ 按 ID 订阅与分发
    └─ 有序停止与物理总线关闭
    ▼
python-can / Panda / 硬件适配器
```

## 功能页面

| 页面 | 主要用途 |
| --- | --- |
| 帧监视（FRAMES） | 实时帧监视、过滤、导入和导出 |
| 信号分析（SIGNALS） | 信号解析、位域查看和解码 |
| 曲线绘制（PLOT） | 信号曲线、统计和时间序列分析 |
| 人工智能引擎（AI ENGINE） | 人工智能辅助解释、上下文和报告 |
| DBC 构建（DBC BUILDER） | DBC 创建、编辑和验证 |
| 代码生成（CODE GEN） | 根据数据库和协议生成代码 |
| 智能分析（INTELLIGENCE） | 异常、聚类和未知信号分析 |
| 帧注入（INJECTION） | 受 ARM 保护的周期/单帧注入 |
| 诊断（DIAGNOSTICS） | UDS/ISO-TP 诊断请求与响应 |
| 仪表盘（DASHBOARD） | 自定义仪表盘和实时指标 |
| 自动逆向（AUTO-RE） | 自动逆向和字段候选识别 |
| 时间线（TIMELINE） | 日志时间线、回放和事件定位 |
| OBD-II 诊断（OBD-II） | OBD-II 服务与 PID 辅助 |
| 机器学习智能（ML INTEL） | 机器学习特征和分类辅助 |
| 网关（GATEWAY） | 双通道转发与路由实验 |

## 支持的数据与接口

日志和数据库：SavvyCAN CSV、candump `.log`、pcap/pcapng、BLF、ASC、MDF4、openpilot `rlog/qlog`（按可用依赖启用），以及 DBC、ARXML、CAN Matrix 等格式。

硬件和服务：

- 通过 `python-can` 支持 SocketCAN、PCAN、Vector、virtual、serial/slcan 等接口。
- 支持 Panda 适配器和项目内的硬件抽象层。
- REST 服务默认绑定本机回环地址，可配置令牌；`POST /inject` 仍受 ARM 保护。
- 提供 MCP 服务，供自动化工具调用分析能力。

## 安全边界

本工具可能向真实 CAN 总线发送数据。请只在隔离台架、仿真器或明确授权的测试环境使用。

- 发送默认关闭，必须显式启用 ARM；取消 ARM 会停止发送。
- 诊断和注入操作会显示确认或安全提示。
- 不建议在行驶中的车辆上运行，也不提供量产刷写、标定或安全绕过保证。
- 使用硬件前请确认终端电阻、供电、总线速率和收发器连接正确。

## 从源码运行

```powershell
git clone https://github.com/yjw17694927050-art/CAN-Space.git
cd CAN-Space
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd canlab
python main.py
```

Linux/macOS：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd canlab
python main.py
```

部分硬件、MDF4、视觉和 AI 功能依赖额外驱动或可选 Python 包；缺少可选依赖时，基础离线分析仍可运行。

## 测试与验证

在 Windows PowerShell 中：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m compileall -q canlab tests
.\.venv\Scripts\python.exe -m pytest tests -q -rs
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

截至 2026-09-14 的本地验证结果为 **287 个通过、1 个跳过**。跳过项是视觉参考测试，原因是当前环境未安装 OpenCV/RapidOCR；测试数量会随回归用例变化，请以 `pytest -rs` 的实际输出为准。

回归测试覆盖 CAN 单一接收者、发送 ARM、诊断事务锁、worker 停止、帧数上限、GitHub 内容校验、REST 生命周期以及跨平台路径行为。

## 当前限制

- 尚未覆盖所有真实车辆、硬件型号和极端总线负载场景。
- 部分信号识别和异常检测仍是启发式结果，需要人工确认。
- ARXML 导出属于实验性能力，未承诺覆盖完整 OEM schema。
- MDF4、视觉和部分 AI 能力依赖可选包；当前仓库不提供二进制安装包。

## 上游、许可证与贡献

- 上游项目：[Sherin-SEF-AI/CANlab](https://github.com/Sherin-SEF-AI/CANlab)
- 当前仓库：[yjw17694927050-art/CAN-Space](https://github.com/yjw17694927050-art/CAN-Space)
- 本项目遵循上游 MIT 许可证；新增代码和文档请继续保留原作者及许可证信息。

欢迎提交问题（issue）和拉取请求（pull request）。涉及真实总线、诊断和硬件的改动，请同时附上仿真或离线回归测试结果。
