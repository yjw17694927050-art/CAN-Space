# CAN-Space — 路线图 ROADMAP

> 由 **PRD.md** 派生。排期与工期为**估算值（受开发进度、需求变化影响）**，不是承诺。每阶段含明确的退出标准（Exit Criteria）以便验收。

项目基于上游 **CAN-Space**（Sherin-SEF-AI/CAN-Space，MIT）二次开发。详见 PRD.md §0。

阶段命名：**P = 基建（Foundation）、E = 体验（Experience）、D = 数据（Data）、C = 商业化（Commercialization）**。
前三个阶段是"把工具打磨成个人工具"；商业化是独立长周期阶段，不抢占前三项的工期。

---

## Phase 0 — 收尾基线 / Basline Cleanup（0.5～1 周）

**目标**：把代码库稳定在当前提交对应的"已审查、已测试"状态，作为后续所有改造的基线。

- [x] 确认工作目录更名 `CAN-Space` 与 git 一致（目录 CAN-Space / 仓库 yjw17694927050-art/CAN）。
- [x] 补全版本号、`canlab.spec` 打包配置检查（PyInstaller 6.22.2 实跑构建成功，产物 32.1 MB 冒烟启动正常）。
- [x] 确认测试基线 **169 passed / 1 skipped** 稳定可复现（超过原 148/2 基线）。
- [x] 建立分支约定（`main` 稳定 / `dev` 或 `feature/*` 开发，已写入 `个人开发规范.md` §2.4，dev 分支已创建）。

**退出标准**：`git status` 干净；`.venv` 下 `pytest tests/ -q` 复现基线；本地能 `python main.py` 启动。

---

## Phase 1 — 地基 Foundine（2～3 周）｜ 对应 PRD R1.4 + R3.1

**目标**：先修"地基"（去锁定、通用 AI 层、i18n 基建），避免后面返工。

### 1.1 去车型锁定（PRD R1.4）
- [x] 抽离 `ai_client.py` 中硬编码的 `SYSTEM_PROMPT`（Hyundai/Kona）。
- [x] 引入"车型知识包 / vehicle knowledge pack"概念：车型特征(总线速率、字节序、counter/checksum 位置习惯)为可配置 JSON，AI 提示词按所选包组装（`core/vehicle_pack.py` + `canlab/vehicle_packs/*.json`；`AIWorker.vehicle_pack` 参数驱动）。
- [x] 提供默认通用包（不指定车厂）。
- [ ] （后续任务）设置页/模型配置处提供"车型知识包"下拉选择，落地"所选包"的用户侧切换。

### 1.2 通用 AI Provider 抽象层（PRD R3.1）
- [x] 新增 `_run_openai_compatible()`：base_url + api_key + model 三参数即可复用任一 OpenAI 兼容端点（基于 `requests` 流式 SSE，不新增 openai 依赖）。
- [x] 把 Anthropic / Groq / OpenAI-兼容 统一进一个 provider 注册表（config 驱动，消除 `ai_client.py` 平铺 if/elif）：`ProviderSpec` + `PROVIDERS` + `get_provider()`，`run()` 按 `spec.kind` 分发。
- [x] 保留对已有 provider 的兼容（老配置不破坏）：Groq 独立 groq_key 兼容、Ollama 免鉴权、Anthropic 路径不变、默认模型取自注册表。
- [ ] （后续任务）设置页/模型配置：为每 provider 提供独立 base_url / api_key / model 编辑与下拉（归入 P2 · R3.3）。

### 1.3 i18n 基建（PRD R1.1 / R1.2）
- [x] 确定语言包方案（自建轻量 dict 语言包：`core/i18n.py`，`tr()` 调用，未命中回退英文/键名，保证不破界面；无 GUI 依赖、headless 可测）。
- [x] 提取全部界面文案到语言包；第一版只出中文一套。——（已完成：窗口标题、15 标签页名、设置页 AI/语言标签；全部 15 个标签页正文（frames/signals/plot/id/inspector/code_gen/dbc/ai/intel/sintel/injection/diagnostics/gateway，及 dashboard/auto_re/timeline/obd 由 `tr()` 回退兜底）逐字符串提取完成，主语言默认中文）
- [x] 设置页加入"语言"切换（中文/English；QSettings 持久化，启动加载，默认 zh；AI 引擎系统提示词语言跟随界面语言，落地 PRD R1.3）。
- [x] （衍生）AI 引擎输出语言跟随界面语言（R1.3 落地，见上）。

**退出标准**：换车型/换 provider 均不改代码；界面文案全部可翻译、主语言切中文可用；原 `main.py` 启动正常；测试通过无回归。

---

## Phase 2 — 体验 Experience（3～4 周）｜ 对应 PRD R2 + R3.2/3.3

**目标**：让工具"简单顺手"并接入国产模型。

### 2.1 界面简化（PRD R2，方案 A）
- [ ] 主窗口改造为"**精简模式**"：默认只显示 采集/回放/帧表格/实时信号 4 块。
- [ ] 其余进阶标签页收进"**高级模式**"折叠菜单，默认隐藏但不删除功能。
- [ ] 每个保留 tab 做"默认即可用"：常用操作首屏，深层选项收纳。
- [ ] （可选）首次启动最小引导：采样→采集→分析→出 DBC。

### 2.2 国产大模型接入（PRD R3.2/3.3）
- [ ] 按序接入：通义千问(DashScope) → DeepSeek → Kimi(Moonshot) → 智谱 GLM → 豆包/火山方舟（至少 3 家先行）。
- [ ] 本地 Qwen 依托已有 Ollama 支持（零成本）验证。
- [ ] 设置界面：每 provider 独立 base_url / api_key / model 配置。

### 2.3 可信度基建（汽车测试工程师视角的可靠底线）
- [ ] 时间戳标注来源（PC 时间 vs CAN 硬件时间戳）并可视化区分。
- [ ] 增加 总线负载率 / bus-off / 采样率 / 丢帧率 显示。
- [ ] 统一结构化日志落盘（改现状分散的错误提示）。

**退出标准**：5 分钟内能完成"加载样例→帧表格→出 DBC"；≥3 家国产模型可用；单界面能读总线健康状态；测试通过。

---

## Phase 3 — 数据资产 Data（3～4 周）｜ 个人工具的核心沉淀

**目标**：把"临时采集"变成"可检索、可复现的个人知识资产"，这是后续商业化的硬通货。

- [ ] **会话存档**：每次采集保存环境信息(时间/车型/操作/硬件)，形成检测记录（证据链雏形）。
- [ ] **信号指纹库**：已确认信号存为指纹(车型+ID+字节布局)，同车型二次匹配秒出。
- [ ] **多 ECU 关联**：同一时间窗内哪些 ID 联动（补齐单 ID 逐帧看的低效）。
- [ ] **标准格式导出强化**：确保 Vector/CANoe、CANdb++、openpilot 等导出在真实工具里可用（这是被企业采用的门槛）。

**退出标准**：能从历史会话一键复用已确认信号；能导出一份在 CANoe 中可打开的 DBC；一份检测记录可回放复现。

---

## Phase 4 — 商业化验证 Commercialization（3～6 个月，独立）

**前置 Gate（不满足则不动工）**：
- [ ] 已完成 P2/P3（去锁定、可信度、数据资产）。
- [ ] 已有一定用户/试用者/数据反馈。
- [ ] 已评估合规边界（PRD R4 合规要点），并咨询专业人士。

**路径与动作**：
- [ ] **开放核心 Open Core**：免费核心(AI 云额度、云信号库、团队协作、企业诊断包、技术支持)收费。
- [ ] **企业/顾问服务试点**：软件开源引流 + 帮车企/供应商搭建逆向产线/数据标注/方案咨询。
- [ ] 商业化 MVP：授权机制、可选安装包(官方 Windows 打包)、付费入口。
- [ ] （长期可选）硬件绑定套件 / SaaS 云端。

**退出标准（本期）**：选定一种收费方式并跑通"引流→试用→转化"最小闭环；获得首批付费或付费意向反馈（而非销售额目标）。

---

## 汇总 / Summary

| 阶段 Phase | 内容 | 工期（估算） | 与 PRD 对应 |
|---|---|---|---|
| P0 收尾 | 基线稳定、分支约定 | 0.5～1 周 | —— |
| P1 地基 | 去车型锁定 + 通用 AI 层 + i18n | 2～3 周 | R1.4, R3.1 |
| P2 体验 | 界面简化 + 国产模型 + 可信度 | 3～4 周 | R2, R3.2/3.3 |
| P3 数据 | 会话存档 + 信号指纹 + 多 ECU + 导出 | 3～4 周 | 个人化核心 |
| P4 商业化 | 开放核心 + 企业服务试点 | 3～6 个月（独立） | R4 |

**前端 P1→P3 合计约 2～3.5 个月**（1 人开发，含测试）；每阶段完成后及时提交并同步更新 AGENT/SPEC/PRD/ROADMAP。

---

*ROADMAP 完 / End of ROADMAP*