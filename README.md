# CAN-Space

CAN-Space 是一个面向汽车 CAN 总线分析、诊断和逆向工程的 PyQt6 桌面工具。

本项目以开源 [CanLab](https://github.com/Sherin-SEF-AI/CanLab) 工程为基础进行二次开发。CanLab 提供了 CAN 日志读取、帧和信号分析、DBC 编辑、协议诊断、代码生成、回放注入以及图形化工作台等基础能力；CAN-Space 在此基础上继续完善中文开发体验、总线安全、并发模型、线程生命周期和自动化接口。

> 当前版本主要面向离线日志、仿真器和隔离台架，仍处于 Alpha 阶段。涉及真实车辆时必须先完成风险评估和硬件验证。

## 项目关系

| 项目 | 角色 | 地址 |
| --- | --- | --- |
| CanLab | 上游开源基础工程 | [Sherin-SEF-AI/CanLab](https://github.com/Sherin-SEF-AI/CanLab) |
| CAN-Space | 基于 CanLab 的二次开发版本 | [yjw17694927050-art/CAN-Space](https://github.com/yjw17694927050-art/CAN-Space) |

本仓库应保留 CanLab 的原作者版权和许可证文本。正式发布前请以 CanLab 仓库中的实际许可证文件为准，并在发布说明中记录对应的上游版本或提交号。

## 目录

- [CanLab 基础工程介绍](#canlab-基础工程介绍)
- [CAN-Space 做了哪些优化](#can-space-做了哪些优化)
- [系统结构](#系统结构)
- [功能模块](#功能模块)
- [支持的数据和接口](#支持的数据和接口)
- [安装和运行](#安装和运行)
- [配置参考](#配置参考)
- [快速上手示例](#快速上手示例)
- [测试和持续集成](#测试和持续集成)
- [开发者指南](#开发者指南)
- [安全边界和已知限制](#安全边界和已知限制)
- [版本和发布流程](#版本和发布流程)
- [许可证和贡献](#许可证和贡献)

## CanLab 基础工程介绍

CanLab 是本项目的 CAN 逆向工程工作台。核心入口位于 `canlab/main.py` 和 `canlab/mainwindow.py`，主要包含：

- **图形界面**：基于 PyQt6，提供帧监视、信号分析、曲线绘制、仪表盘、时间线和网关等功能页。
- **协议和分析引擎**：包含 UDS、ISO-TP、OBD-II、J1939、XCP、DoIP，以及计数器、校验和、信号边界、聚类和异常分析辅助。
- **数据库和工程文件**：支持 DBC、ARXML、CAN Matrix 等格式，并可保存为 `.canlab` 项目文件。
- **数据处理**：支持常见 CAN 日志格式导入、过滤、回放、导出和离线分析。
- **扩展接口**：提供插件目录、REST 接口和 MCP 服务，便于自动化工具接入。
- **硬件抽象**：通过 `python-can`、Panda 及其他适配器连接 CAN 硬件或虚拟总线。

## CAN-Space 做了哪些优化

### 1. 统一 CAN 总线所有权

- 新增 `CanCoordinator`，统一管理物理总线、接收线程、订阅分发和关闭顺序。
- 同一物理总线只保留一个接收线程，避免多个线程同时 `recv()` 导致竞争和丢帧。
- 双通道网关为每条物理总线分别维护接收线程，不共享不明确的全局接收状态。

### 2. 统一发送安全门

- 通过 `SafeBusAdapter` 统一所有发送入口。
- 注入、回放、模糊测试、网关转发、REST `/inject` 和诊断发送都必须先显式启用 ARM。
- 取消 ARM 后立即拒绝新的发送请求，避免 GUI、脚本或协议模块绕过安全控制。

### 3. 改进诊断和后台任务并发

- 注入和 DTC 扫描放入后台 worker，避免阻塞 PyQt6 主线程。
- 同一诊断通道的请求/响应使用事务锁，避免并发请求串包。
- DTC 清除只接受 UDS `0x54` 正响应，不把其他响应误判为成功。
- 等待、周期任务和 worker 停止均可被唤醒，窗口关闭时不会长时间卡住。

### 4. 增加日志帧数硬上限

- 文件导入、文本导入、批量回放、分析和绘图入口统一执行 `max_frames` 限制。
- 超过上限时保留最新的 N 帧，并在结果元数据中报告截断状态和时间戳来源。
- 使用惰性分块读取和有界缓存，降低大日志导入时的内存峰值。
- `max_frames <= 0` 视为无效配置并抛出 `ValueError`。

### 5. 加强 GitHub 内容校验

- GitHub 读取范围限定为分支、目录树或文件，避免把任意 API 路径当成文件。
- 对仓库、分支、路径和 SHA 做身份校验。
- 增加编码处理、文件大小限制、原子写入和 SHA-256 校验，避免不完整下载覆盖缓存。

### 6. 完善中文和自动化使用体验

- README、测试说明和安全提示以中文为主，代码类名、协议名和命令保持原样，方便搜索和执行。
- 保留人工智能上下文、机器学习辅助、视觉参考、REST 和 MCP 等扩展能力。
- 增加针对总线访问、worker 生命周期、REST 生命周期和帧数上限的回归测试。

## 系统结构

```text
PyQt6 图形界面和功能页
          │ 信号/槽，不直接执行 CAN 输入输出
          ▼
AppState + CanCoordinator
          ├─ 唯一物理总线所有者
          ├─ 唯一接收线程
          ├─ ARM 安全发送入口
          ├─ 按 ID 订阅和分发
          └─ 有序停止和总线关闭
          ▼
python-can / Panda / 硬件适配器 / 虚拟总线
```

## 功能模块

| 模块 | 说明 |
| --- | --- |
| 帧监视 | 实时帧查看、过滤、导入和导出 |
| 信号分析 | 信号解析、位域查看和解码 |
| 曲线和时间线 | 信号曲线、统计、回放和事件定位 |
| 智能分析 | 未知信号、聚类、异常和字段候选识别 |
| DBC 构建 | DBC 创建、编辑、验证和导出 |
| 代码生成 | 根据数据库和协议生成代码 |
| 诊断 | UDS、ISO-TP、OBD-II 等诊断请求与响应 |
| 帧注入和回放 | 受 ARM 保护的单帧、周期帧和日志回放 |
| 仪表盘 | 自定义仪表盘和实时指标 |
| 网关 | 双通道转发和路由实验 |
| 人工智能/机器学习 | 上下文构建、辅助解释和分类分析 |

## 支持的数据和接口

- 日志：SavvyCAN CSV、candump `.log`、pcap/pcapng、BLF、ASC、MDF4、openpilot `rlog/qlog`（按依赖启用）。
- 数据库：DBC、ARXML、CAN Matrix 等格式。
- 硬件：通过 `python-can` 支持 SocketCAN、PCAN、Vector、virtual、serial/slcan 等接口，并支持 Panda 适配器。
- 自动化：REST 接口默认绑定本机回环地址，可配置令牌；MCP 服务可供外部工具调用分析能力。

### 兼容性矩阵

下表是当前代码和依赖定义的兼容范围；具体硬件仍需在目标环境实测并记录驱动版本。

| 项目 | 当前信息 |
| --- | --- |
| 操作系统 | Windows、Linux、macOS（PyQt6 和 `python-can` 支持范围内） |
| Python | 推荐 Python 3.11 及以上；当前开发环境为 Python 3.12 |
| 虚拟总线 | `vcan`、`virtual` 等 `python-can` 后端 |
| 常见硬件 | SocketCAN、PCAN、Vector、Panda；具体型号取决于驱动 |
| 可选格式 | MDF4 需要 `asammdf`；视觉参考需要 OpenCV/RapidOCR |

首次在新硬件上使用时，请记录操作系统、Python、`python-can`、厂商驱动、总线速率和终端电阻配置。

## 安装和运行

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

MDF4、视觉、人工智能和部分硬件功能依赖可选 Python 包或驱动；缺少可选依赖时，基础离线分析仍可运行。

## 配置参考

设置窗口提供语言、车辆包、人工智能服务、缓存目录、REST 端口和插件查看等选项。配置由 Qt `QSettings("CAN-Space", "CAN-Space")` 保存；敏感密钥使用系统密钥环保存，不应写入仓库或日志。

| 配置项 | 默认值/位置 | 说明 |
| --- | --- | --- |
| 界面语言 | 中文 | 可切换中文和英文 |
| 车辆包 | `generic` | 从 `canlab/vehicle_packs/` 加载 |
| 缓存目录 | `~/.canlab/cache` | GitHub、数据库等缓存；清理操作限制在 `~/.canlab` 内 |
| 插件目录 | `~/.canlab/plugins/*.py` | 只加载用户明确批准的插件 |
| REST 地址 | `127.0.0.1:8765` | 含发送接口时禁止绑定非本机地址 |
| AI 密钥 | 系统密钥环 | 支持的提供商和模型以设置窗口实际列表为准 |
| GitHub 令牌 | 系统密钥环 | 仅用于需要认证的仓库读取 |

## 快速上手示例

1. 启动应用后先阅读安全提示，保持 ARM 发送开关关闭。
2. 在“帧监视”页面导入 `canlab/sample_data/` 中的样例日志。
3. 使用过滤器定位目标 CAN ID，切换到“信号分析”或“智能分析”查看候选字段。
4. 在“DBC 构建”页面人工确认信号定义并导出 DBC。
5. 仅在虚拟总线或隔离台架上启用 ARM，再使用“回放/注入”验证结果。

离线命令行解析示例：

```powershell
cd canlab
python -c "from core.log_parser import parse_log_file; print(parse_log_file('sample_data/sample_kona_drive.csv').head())"
```

样例文件名可能随版本变化，请以 `canlab/sample_data/` 中的实际文件为准。

## 测试和持续集成

本地验证：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m compileall -q canlab tests
.\.venv\Scripts\python.exe -m pytest tests -q -rs
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

截至 2026-09-14，本地验证结果为 **287 个通过、1 个跳过**。跳过项是视觉参考测试，原因是当前环境未安装 OpenCV/RapidOCR；测试数量会随回归用例变化，请以 `pytest -rs` 的实际输出为准。

仓库已提供 `.github/workflows/ci.yml`，用于编译检查、测试和打包冒烟检查。提交代码前请先在本地通过完整测试；涉及 CAN 发送、线程或 REST 生命周期的改动，应同时增加回归测试。

### 日志和问题报告

应用事件日志默认写入 `~/.canlab/logs/events-YYYYMMDD.jsonl`。提交问题时请优先附上：复现步骤、脱敏后的日志、操作系统和 Python 版本、硬件/驱动信息、是否启用 ARM，以及完整的 pytest 结果。不要上传 API 密钥、车辆识别信息或未经授权的真实总线数据。

## 开发者指南

```text
canlab/main.py              应用入口和安全提示
canlab/mainwindow.py        主窗口、菜单和页面装配
canlab/core/                 协议、解析、状态和服务层
canlab/tabs/                 各功能页面
canlab/panels/               可复用面板
canlab/ui/                   worker、动画和界面辅助
canlab/vehicle_packs/        车辆配置包
tests/                       单元测试和回归测试
```

建议的扩展方式：

- 新增协议：将收发和解析逻辑放在 `canlab/core/`，通过 `CanCoordinator` 获取总线，不直接创建竞争性的接收线程。
- 新增页面：在 `canlab/tabs/` 实现 QWidget，耗时操作放入 worker，并在关闭路径中停止 worker。
- 新增插件：放入 `~/.canlab/plugins/`，只启用可信文件；插件不得绕过 ARM 安全门。
- 新增测试：优先使用虚拟总线和 mock，不依赖真实车辆；对发送路径、异常路径和停止路径分别覆盖。

## 安全边界和已知限制

- 发送默认关闭，必须显式启用 ARM；请只在隔离台架、仿真器或明确授权的测试环境使用。
- 不建议在行驶中的车辆上运行，也不提供量产刷写、标定或安全绕过保证。
- 尚未覆盖所有真实车辆、硬件型号和极端总线负载场景。
- 部分信号识别和异常检测是启发式结果，需要人工确认。
- ARXML 导出属于实验性能力；MDF4、视觉和部分人工智能功能依赖可选包。
- 当前仓库不提供二进制安装包。

## 版本和发布流程

当前项目尚未形成自动发布流程。建议每次发布按以下步骤执行：

1. 更新版本号和变更日志，注明对应的 CanLab 上游版本/提交号。
2. 执行完整测试、静态检查、打包检查和 `git diff --check`。
3. 在虚拟总线或隔离台架完成最小冒烟测试，记录操作系统、Python、驱动和硬件信息。
4. 创建 Git 标签和 GitHub Release，附上变更摘要、已知限制、校验和及许可证信息。
5. 对涉及安全边界的改动，提供回滚方案和明确的升级提示。

## 许可证和贡献

- 上游工程：[Sherin-SEF-AI/CanLab](https://github.com/Sherin-SEF-AI/CanLab)
- 当前工程：[yjw17694927050-art/CAN-Space](https://github.com/yjw17694927050-art/CAN-Space)
- 本项目应遵循 CanLab 上游适用的许可证，并在分发时保留原作者版权和许可证文本；正式发布前请核对上游 `LICENSE` 文件。

欢迎提交问题和拉取请求。涉及真实总线、诊断和硬件的改动，请同时附上仿真或离线回归测试结果。
