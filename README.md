# IEC 61850 客户端 GUI 工具

基于 Python + ttkbootstrap 的 IEC 61850 客户端图形界面，通过 **ctypes 链接 libiec61850 动态库**（`iec61850.dll` / `libiec61850.so`）实现，不依赖项目源码编译。

## 功能（对应 examples 中各客户端示例）

| 标签页 | 功能 | 对应示例 |
| --- | --- | --- |
| 📂 数据浏览 | 树形浏览服务器模型（LD→LN→DO→DA 懒加载），"选中即读"、大字值显示、读值历史、智能写值 | client_example1、example_array |
| 📋 数据集 | 读取数据集成员及实时值，支持单成员/整组写值 | client_example4 |
| 🎛 控制操作 | 直控 / SBO（先选择后操作）、操作来源、联锁/同期校验、操作日志 | client_example_control |
| 📡 报告订阅 | 扫描 RCB（BRCB/URCB）、订阅报告、总召(GI)、实时事件表格 | client_example_reporting |
| 🗃 文件服务 | 浏览服务器文件、下载、上传、删除 | file-tool |
| 🗺 点表映射 | 模型快照浏览/搜索、语义别名编辑（人工确认）、映射规则启停/增删、SCD desc 导入 | — |
| 🤖 AI 助手 | **自然语言对话操作 IED**：模型问答、读值诊断、报告分析、遥控（需人工确认） | — |

## 运行

```bash
pip install ttkbootstrap

python main.py [服务器IP] [端口]
# 例: python main.py 192.168.31.57 102
```

程序启动默认**最大化窗口**。

## AI 助手使用说明

在 GUI 内置的 LLM Agent，通过**工具调用**直接操作当前 IEC 61850 连接，
不需要 MCP、不需要额外进程。

### 配置

1. 连接目标 IED 服务器（未连接时也可以对话，但工具会提示先连接）
2. 切到 "🤖 AI 助手" 页，填写：
   - **接口地址**：任意 OpenAI 兼容端点（见下表）
   - **API Key**：在各服务商平台自行申请，手动粘贴（明文保存在 `ai_settings.json`，注意保密）
   - **模型**：点 **⟳ 获取模型** 从服务端 `/models` 拉取后下拉选择（也可手动输入）
3. 输入框输入问题，回车发送（Shift+回车换行）

| 服务商 | 接口地址 | 模型示例 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5:7b`（Key 任意） |
| vLLM | `http://<主机>:8000/v1` | 部署的模型名 |

### Agent 可用的工具

| 工具 | 能力 | 安全级别 |
| --- | --- | --- |
| `list_model` / `list_datasets` / `list_rcbs` | 枚举服务器模型、数据集、RCB | 只读 |
| `read_value` | 读取任意数据属性当前值 | 只读 |
| `write_value` | 写数据属性（写前校验引用存在于服务器模型） | 写操作 |
| `operate_control` | **遥控操作**（直控/SBO） | **危险：必须经弹窗人工确认** |
| `watch_reports` | 订阅 RCB 监听 N 秒，收集报告用于分析 | 只读 |
| `list_files` | 列出服务器文件目录 | 只读 |

### 安全机制

- **遥控人工确认**：LLM 发起 `operate_control` 时弹窗展示操作对象和值，用户点"是"才执行
- **防幻觉校验**：读写前用服务器模型缓存校验引用存在性，LLM 编造的引用会被直接拒绝
- **串行化**：同一连接的所有 MMS 请求经锁串行执行，避免并发请求冲突
- **未连接保护**：未连接 IED 时仍可对话（例如询问配置方法），但数据类工具会明确告知需先连接

### 使用示例

```
"读一下 SPCSO1 的开关位置"
"这个服务器有哪些数据集？分别包含什么成员？"
"订阅 EventsBRCB01 监听 5 秒，告诉我收到了什么报告"
"帮我把 SPCSO1 置位"        → 会弹窗要求确认
```

## 点表映射与本地持久化（data/point_map.db）

61850 模型中的点名（如 `simpleIOGenericIO/GGIO1.SPCSO3`）没有可读语义，
本工具通过 SQLite 数据库（`data/point_map.db`，Python 标准库，无额外依赖）
建立"模型点 → 人类可读语义"的映射。数据库分**三张表**：

### 1. `model_nodes` —— 模型快照表

**来源：自动生成**。每次 GUI 连接服务器成功后（扫描链最后一步）自动写入/刷新，
也可用 `ModelStore.scan_model(client, server_id)` 手动触发。

| 列 | 含义 |
| --- | --- |
| `ref` | 完整引用 `LD/LN.DO`，主键，如 `simpleIOGenericIO/GGIO1.SPCSO3` |
| `server_id` | 服务器标识 `IP:端口`，隔离多台 IED |
| `ld_name` / `ln_name` | 逻辑设备名 / 逻辑节点名 |
| `ln_class` | LN 类（`GGIO`、`MMXU`、`XCBR`…），重要语义线索 |
| `do_name` | 数据对象名，如 `SPCSO3` |
| `do_type` | 从 DO 名推断的 CDC 类型（`SPC`/`DPC`/`MV`/`ENS`…，尽力推断） |
| `fcs` | 功能约束集合，如 `CO,ST`（由带 FC 目录提取） |
| `attrs` | 带 FC 的属性目录原文（`$` 分隔） |
| `scanned_at` | 最近扫描时间戳 |
| `stale` | 1 = 本次扫描未出现（模型变化/点消失），**只标记不删除** |

### 2. `point_semantics` —— 语义映射表

**来源：人工 / SCD 导入 / 规则生成**，按 `ref`（大小写不敏感）关联快照。

| 列 | 含义 |
| --- | --- |
| `ref` | 主键，与 `model_nodes.ref` 对应 |
| `alias` | 中文别名（给人和 AI 助手看的名字，如 "1号开关遥控"） |
| `description` | 自由文本描述 |
| `category` | 分类：开关量 / 遥测 / 遥信 / 保护… |
| `tags` / `unit` / `scale` / `alarm_level` | 自由标签、工程量单位/系数、告警等级 |
| `origin` | 语义来源：`manual`（人工）> `imported`（SCD desc）> `rule`（规则）> `ai_suggest`（预留） |
| `updated_at` / `stale` | 更新时间 / 模型中已不存在 |

**覆盖规则**：人工语义（`manual` 且有别名）永不被规则或 SCD 覆盖；
SCD 导入默认跳过已导入条目，加 `--overwrite` 才重新导入。

### 3. `mapping_rules` —— 映射规则表

**来源：内置 18 条默认规则 + 用户自定义**，用于批量给快照点打默认语义
（`origin='rule'`）。

| 列 | 含义 |
| --- | --- |
| `pattern` | 匹配模式（如 `SPCSO`、`MMXU`） |
| `match_on` | 匹配方式：`ref`（引用包含）/ `do_type`（CDC 相等）/ `ln_class`（LN 类相等） |
| `alias_tpl` / `desc_tpl` / `category` | 命中后写入的别名 / 描述 / 分类 |
| `priority` | 优先级，大者优先；同级时更具体的匹配方式优先（do_type > ln_class > ref） |
| `enabled` / `built_in` | 是否启用 / 是否内置（内置规则只能停用不能删除） |

### 使用方式

- **GUI（自动）**：连接成功后状态栏显示
  `点表映射已同步：N 个数据对象入库（IP:端口），规则生成 M 条语义`；
  在"📂 数据浏览"页选中任意 DO/DA，右侧绿色 🏷 行显示别名/分类/描述
- **SCD 导入（推荐，语义最权威）**：
  ```bash
  python -m core.scd_import 工程.scd --server 192.168.0.10:102
  # 可选: --ied IED1 只导入某装置；--overwrite 覆盖已导入条目
  ```
- **代码 API**：`scan_model` / `apply_rules` / `set_semantics` / `lookup` /
  `get_nodes` / `list_semantics` / `stats` 等（见 `core/model_store.py`）

### 多服务器与数据一致性

- 每台 IED 按 `server_id`（`IP:端口`）隔离，互不影响
- 同一服务器重新连接时增量 upsert：新增点插入、消失点标 `stale=1`（语义保留）
- SCD 导入时用 `--server` 指定与 GUI 连接相同的 `server_id`，语义即可与快照对齐
- 自检测试：`python tests\test_model_store.py`、`python tests\test_scd_import.py`



1. 程序目录
2. `../build_iec61850_vs2022/src/Debug`
3. `../libiec61850-1.6/MMSFileUI`
4. `../libiec61850-1.6/build_win_vs2022/src/Debug`、`build2/src/Debug`、`build/src`
5. 系统搜索路径

某个 dll 损坏或位数不符时会自动尝试下一个候选。也可以直接把 `iec61850.dll` 复制到本目录。

## 项目结构（低耦合）

```
IEC61850ClientGUI/
├── core/                  # 封装层（无 GUI 依赖，可独立复用）
│   ├── ffi.py             # ctypes 绑定：签名、错误码、枚举常量
│   ├── mms_value.py       # MmsValue <-> Python 值互转
│   ├── connection.py      # 连接 + 模型浏览 + 读/写 + 全模型枚举
│   ├── model_store.py     # 点表映射持久化（快照/语义/规则三张表，SQLite）
│   ├── scd_import.py      # SCD/CID/ICD desc 导入器
│   ├── dataset.py         # 数据集服务
│   ├── control.py         # 控制操作（直控/SBO）
│   ├── reports.py         # RCB 订阅（原生回调 -> Python 回调）
│   └── files.py           # MMS 文件服务（列目录/下载/上传/删除）
├── gui/                   # ttkbootstrap 界面层
│   ├── app.py             # 主窗口 + 连接管理 + 线程调度
│   └── tabs/              # 五个功能标签页（互不依赖，均只依赖 app 接口）
└── main.py                # 入口
```

`tests/` 为不依赖真实 IED 的自检测试（FakeClient 模拟服务器）与联机验证脚本
`verify_live.py`。

## 技术说明

- 所有阻塞的 MMS 服务调用都在**工作线程**执行，报告回调发生在库内部线程，
  两者均经消息队列转发到主线程更新 UI，界面不卡顿
- 读到的值自动按 MMS 类型转换（布尔/整数/浮点/字符串，结构体与数组递归展开为列表）
- 写值时自动识别输入：`true/false` → 布尔，整数/浮点 → 数值，其余 → 字符串

## 已验证（对 libiec61850 自带示例服务器实测）

- 模型浏览（LD/LN/DO/DA）与读值 ✔
- 数据集读取（IED1LD1/LLN0.AnalogEvents）✔
- RCB 订阅收到实时报告 5 条 ✔
- SPCSO1 控制操作成功，stVal 变为 True ✔
- 文件服务：列目录 / 下载（内容比对一致）/ 上传 / 删除 ✔

> 提示：`server_example_files` 服务器要求运行目录下存在 `vmd-filestore/`
> 文件夹，否则文件目录服务会返回"类型不匹配"错误（IED_ERROR 22）。

