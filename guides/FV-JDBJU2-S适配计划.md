# FV-JDBJU2-S 系列适配计划

状态：已实现 profile 能力声明、共享设备层、基本模式、风向、送风方式、运行时长及诊断状态，真机验证待完成。工作分支：`feat/fv-jdbju2-s`。下面保留实施设计；最终支持范围及限制以 README 与仪表盘卡片说明为准。用户确认 JDBJU2-S 无照明和音响，因此不会开放这两项；风量默认禁用，气味感应按硬件标志条件创建。

## 范围

首版新增独立 profile，支持 FV-JDBJU2-S 的设备发现、状态读取、待机、取暖、换气、凉干燥、热干燥。风向使用 climate 的摆风接口，送风方式与运行时长使用 select 实体；风量 select 默认禁用。功能是否存在、字段、编码和模式限制均由 profile 声明；通用 adapter 负责创建 HA 实体。复用账号登录、配置流程、设备 token 和 API 请求框架。

首版只开放有型号依据的 `JDBJU2-S`、`FV-JDBJU2-S`。App 将 TB30U2-W 导向同一控制页面，但不因此开放整个 0820 品类或其他型号。该型号不声明照明、音响；纳诺怡等只有共用页面分支、没有该型号功能入口依据的模式不开放。运行时长表示运行多久后停止，不是预约启动时间。

## 协议依据

参考源码位于 `~/workbench/panasonic_code/sources/`，不将反编译源码复制到本仓库。

| 依据 | 结论 |
| --- | --- |
| `cn/pana/caapp/commonui/util/CommonUIJumpUtils.java` | JDBJU2-S 与 TB30U2-W 使用 SmallBathHeatStartActivity |
| `cn/pana/caapp/cmn/communication/Common.java` | 状态接口 ADevGetStatusInfoSmallBath，控制接口 ADevSetStatusInfoSmallBath |
| `cn/pana/caapp/yuba/net/NetRequestMgr.java` | 顶层 id、usrId、deviceId、token；控制字段置于 params；id 来自消息计数 |
| `cn/pana/caapp/yuba/util/ParamSettingUtil.java` | 使用设备 ID 哈希 token；控制参数由 HiddenBathHeatSetStateBean 生成 |
| `cn/pana/caapp/yuba/view/dialog/SmallBathHeatSelectModeDialog.java` | 取暖 7、换气 3、凉干燥 4、热干燥 5 |
| `cn/pana/caapp/yuba/activity/small/SmallBathHeatPowerStateActivity.java` | 待机 0；模式切换恢复记忆参数；风向记忆值 3 转为 0 |
| `cn/pana/caapp/yuba/a/a.java` | 模式分别读取 remWarm、remVentilation、remCoolDry、remHotDry 对应记忆字段 |
| `cn/pana/caapp/yuba/view/dialog/HiddenBathheatSetTimeDialog.java` | 定时编码 3/6/12/16/22/35 对应 15分钟/30分钟/1小时/3小时/6小时/连续 |
| `cn/pana/caapp/cmn/communication/Communication.java` | 原生请求使用 SmartApp User-Agent 和会话 Cookie |

待确认：实际 category 和设备列表型号字段、token 大小写、请求头兼容性、控制成功响应结构、设备记忆字段是否齐全。0820 为暂定品类，需要实际设备信息确认。

## 实施步骤

### 1. 设备识别与只读联调

- 获取脱敏设备列表及状态样本，保留型号、品类、字段名和字段值，移除账号、SSID、token 等凭据。
- 新增 `profiles/bathroom_heater_0820_fv_jdbju2_s.py`，声明独立接口、型号白名单、climate 平台，复用统一的 `bathroom_heater` 实体类型。
- 在 profile 中声明 `small_bath` 协议标识及型号能力，在 `profiles/__init__.py` 注册 profile。
- 复用现有型号提取流程；只有真实样本证明字段不足时才修改 `config_flow.py`。
- 对照原生请求头，以 profile 的 Cookie 和额外 headers 配置优先解决；不猜测新型号的网页 Referer。
- 状态响应要求 results 对象和 runningMode 字段；新型号的状态和控制响应均按原生逻辑校验 id 与请求一致，不默认接受任意非 JSON 响应。已有型号保持原响应规则。

### 2. 五种基本模式

- 在 `climate.py` 使用基于 profile 的共享状态实体；型号的模式映射和 payload 构造由 profile 声明，已有设备继续使用原 adapter。
- 模式映射：OFF=0、HEAT=7、FAN_ONLY=3、COOL=4、DRY=5。说明 COOL 在此表示凉干燥。
- 当前 RB20VL1 的待机 32、模式 37/38/40/42 和 DIYnext 字段不能用于新接口。
- 控制参数按 App 字段构造：runningMode、windVoSet、warmTempset、windDirectionSet、windKindSet、timeSet、lightSet、speakerSet、odorSensorSet、reserved3 至 reserved10。未修改字段使用 255。
- 切换模式时读取对应 rem* 记忆字段：取暖 remWarm*、换气 remVentilation*、凉干燥 remCoolDry*、热干燥 remHotDry*。换气使用记忆风量；其他模式按原生逻辑跳过风量。
- 定时恢复遵守 App 校验和默认值；缺失字段不可被当作有效零值。明确处理每个模式允许的定时选项，不能将枚举编码视作线性时长。
- 开启优先恢复最近有效模式，否则默认换气；未知模式不能沿用旧的 HA 模式而显示错误状态。
- offline=1 时实体不可用，控制前读取到离线状态时不发送指令。
- 控制成功后重新读取状态，避免将 payload 中的 255 跳过值写入本地状态。只改新 adapter 必需路径，保留现有设备行为。

### 3. 验证与文档

- 增加有意义的协议测试：型号白名单及品类过滤、五种状态解析、记忆参数恢复、定时校验、跳过字段、离线及未知模式、请求失败后不伪造状态。
- 验证现有 0900 和 RB20VL1 profile 的匹配、模式映射及 payload 不受影响。
- 执行 Python 编译检查及相应测试；HA 依赖缺失时明确记录验证范围，不能把静态检查当作运行验证。
- 真机逐项验证五种模式，确认 App 与 HA 双向同步、关机、设备离线恢复、会话过期和命令失败行为。
- 更新 README：真机验证前明确标注实验性适配，与已验证设备分开列出。

### 4. 后续功能

已加入剩余时间、报警、滤网及升级状态码；风量作为实验性能力默认禁用。气味感应按 `gasCheckHas=1` 条件创建，首次读取失败后也能在恢复状态时发现。后续型号必须独立声明其真实能力，不能从共用 App 页面推断照明、音响、纳诺怡等功能存在。

## Profile 能力声明设计（更新后的实施架构）

本节细化并调整上述实施步骤：新型号的差异放入 profile，新增共享设备层，climate 和 select 使用同一状态来源。

当前代码的职责边界：

- `models.py`：纯数据能力及解析规则，包括选项解码、硬件标志判断和数值归一化，不访问网络或 HA 运行状态。
- `profiles/`：型号能力、接口声明、模式字段、定时限制及记忆参数恢复；生成协议 payload，不发送请求。
- `api.py`：请求、响应和业务错误校验，不更新实体状态或决定设备操作。
- `coordinator.py`：共享状态、模式记忆、轮询、事务锁及错误到 HA 的转换；内部控制函数不重复加锁，公开控制入口持有完整事务锁。
- `entity.py` 和各平台实体：设备关联、HA 展示与服务入口，复用能力解析规则，操作交给 coordinator。
- `__init__.py`：账号和设备层的初始化、平台加载、失败与取消时的清理。

### 数据模型

在 `models.py` 增加类型化的可选能力声明，字段命名在实现时统一：

- `select_capabilities`：默认空元组；每项包含稳定 key、翻译 key、状态字段、写入字段、选项编码、适用模式、各模式选项限制以及必要的读值归一化映射。
- 控制声明：写入字段白名单、默认跳过参数、待机值、模式映射、各模式记忆字段及参数恢复规则。
- 设备状态声明：离线字段和值；未知模式不能被当成待机。
- 同一选项的显示文本、状态读取编码、写入编码允许分别声明，避免假设读写完全对称。
- 简单差异采用数据配置；确实需要算法的协议规则放入可测试的 profile 关联函数或协议构造模块。通用实体中不判断具体型号。
- 新字段提供默认值，让现有 profile 无需立即迁移。

### FV-JDBJU2-S 的三个选择能力

| 实体 | 字段 | 编码依据 | 适用模式 |
| --- | --- | --- | --- |
| 风向 | windDirectionSet | 固定=0，自动=6；恢复记忆值3时按 App 转为0 | 取暖、凉干燥、热干燥 |
| 送风方式 | windKindSet | 参数选择对话框：集中=2，扩散=1 | 取暖、凉干燥、热干燥 |
| 运行时长 | timeSet | 15分钟=3、30分钟=6、1小时=12、3小时=16、6小时=22、连续=35 | 四种运行模式 |

取暖仅开放15分钟至3小时；热干燥增加6小时；换气和凉干燥增加6小时与连续。以实际设备验证后的限制为准。

注意：送风方式对话框的选择/写入映射与主页面文字显示存在矛盾（主页面把1显示为集中）。实施前用 App 操作和状态样本确认读写语义，不将矛盾映射直接作为已验证事实。

### 共享设备状态与命令

新增 `coordinator.py`，每台新设备一个 DataUpdateCoordinator，放入账号 runtime 的设备映射。climate、select、sensor 和条件 switch 均订阅它，15秒轮询一次设备，而不是每个实体单独轮询。

共享控制入口负责：

1. 用每设备 asyncio.Lock 串行化“读取最新状态、校验、构造命令、写入、刷新”。
2. 按 profile 校验当前模式、选择项和字段白名单，拒绝不适用的操作。
3. 模式切换时恢复目标模式的合法记忆值；普通 select 操作保持其他字段为255，不额外切换模式或重置无关设置。若原生操作要求关联参数，按已验证规则补充。
4. 刷新与写入共享同一锁，避免较旧的轮询响应覆盖新状态；写入后的读取使用不重复加锁的内部路径，避免死锁。
5. 写入成功后回读真实状态，不把255合入状态。设备延迟生效时先保留实际状态，由后续轮询确认。
6. 将 API 认证失败转换为 ConfigEntryAuthFailed，通信失败转换为更新/服务错误；错误不能被吞掉并向 HA 报告成功。
7. offline=1 时所有关联实体不可用；某个能力不适用当前模式时，仅该 select 不可用。未知字段值显示未知，不猜测为第一项。

首版新设备使用共享层，原有空调和 RB20VL1 保留当前路径；后续迁移可另行处理，避免扩大本次回归范围。

### 通用 HA adapter

- 新增 `select.py`，使用 CoordinatorEntity + SelectEntity。只遍历 profile 的 select_capabilities，不包含型号或字段专用分支。
- profile 未声明能力时不创建实体；某功能只在部分模式可用时保留实体，通过 available 表达当前不可操作。
- 运行时长的 options 根据当前模式动态变化，调用服务时再次根据最新状态校验，防止界面选项过期。
- 新 climate adapter 读取 coordinator 状态，所有模式命令走共享入口；现有 entity kind 的实现不改写。
- select 的 unique_id 使用设备 ID + 稳定能力 key；与 climate 绑定同一设备和账号父设备。
- 在 `__init__.py` 中先创建共享设备对象并完成首次刷新，再转发平台；卸载和重载时释放监听、轮询及 runtime 引用。
- 首次查询暂时失败时保留不可用的 coordinator，允许同账号现有设备正常加载，并由后续轮询恢复；认证失败仍进入账号重新认证。
- profile 声明 climate/select 平台，继续使用现有平台注册逻辑；确认旧配置中存储的平台信息不会阻止新平台加载。
- `translations/zh-Hans.json` 补充实体名称和选项翻译；编码与稳定选项 key 分开，便于翻译。

## 文件改动清单

| 文件 | 计划改动 |
| --- | --- |
| models.py | 能力声明模型、控制规则配置及新 entity kind |
| profiles/bathroom_heater_0820_fv_jdbju2_s.py（新增） | 新型号接口、模式、三个 select 能力、跳过参数、记忆规则 |
| profiles/__init__.py | 注册新 profile，支持平台发现 |
| coordinator.py（新增） | 共享状态、统一轮询、命令锁、错误处理及回读 |
| __init__.py | 新设备 coordinator 的创建、共享和卸载 |
| climate.py | 新设备 coordinator adapter 及实体注册 |
| select.py（新增） | 按 profile 创建通用选择实体 |
| translations/zh-Hans.json | 实体名和选项翻译 |
| api.py | 优先保持原有结构；仅发现请求头或响应校验差异时做必要调整 |
| config_flow.py | 优先保持不变；真实设备发现字段不足时再补充 |
| tests/（新增） | profile、控制规则、共享层与实体联动测试 |
| README.md | 支持范围、模式含义、附加实体及验证状态 |

## 实施批次与验证补充

1. 能力模型和新 profile：核对接口、编码矛盾、模式限制；测试匹配和命令参数。
2. 共享层和 climate：完成首次读取、模式控制、离线和认证处理；验证现有设备路径不变。
3. 通用 select：风向、送风方式、运行时长；验证能力缺省、动态选项及不适用状态。
4. HA 生命周期与真机联调：验证同设备只轮询一次、并发操作顺序、控制期间模式变化、回读失败、卸载重载无残留；更新文档。

测试还需覆盖：不同 profile 声明不同能力时实体数量正确；写入失败不更新状态；跳过值不污染状态；模式切换后合法运行时长选项同步变化；锁不会死锁；状态更新通知到所有关联实体。

## 验收条件

1. FV-JDBJU2-S 能被正确发现和选择；未验证型号不会因同品类被放行。
2. 五种模式在 HA 与 App 中一致；不会发送 RB20VL1 的协议字段或模式值。
3. 模式切换保留无关设置，并正确恢复有效记忆参数。
4. 离线、会话过期、未知状态及控制失败有明确表现，界面不会虚报成功。
5. 现有设备适配无回归，文档准确区分静态协议分析与真机验证。
6. 四个实体共享设备状态与轮询；profile 未声明的能力不会创建实体。
7. 风向、送风方式和运行时长可独立控制，模式限制有效，并发操作不会覆盖无关设置。
