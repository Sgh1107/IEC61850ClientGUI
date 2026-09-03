# IEC 61850 客户端 GUI 工具（agent 分支）

> 本分支在 master 基础上新增了**内置 AI 助手**（LLM + 工具调用，直接操作 IEC 61850 客户端）。
> 其余功能与 master 一致。

基于 Python + ttkbootstrap 的 IEC 61850 客户端图形界面，通过 **ctypes 链接 libiec61850 动态库**（`iec61850.dll` / `libiec61850.so`）实现，不依赖项目源码编译。

## 功能（对应 examples 中各客户端示例）

| 标签页 | 功能 | 对应示例 |
| --- | --- | --- |
| 📂 数据浏览 | 树形浏览服务器模型（LD→LN→DO→DA 懒加载），"选中即读"、大字值显示、读值历史、智能写值 | client_example1、example_array |
| 📋 数据集 | 下拉选择数据集引用（连接后自动扫描），读取成员实时值，支持单成员/整组写值 | client_example4 |
| 🎛 控制操作 | 下拉选择控制对象，直控 / SBO（先选择后操作）、操作来源、联锁/同期校验、操作日志 | client_example_control |
| 📡 报告订阅 | 下拉选择 RCB（连接后自动扫描全部 BRCB/URCB）、订阅、总召(GI)、实时事件表格 | client_example_reporting |
| 🗃 文件服务 | 浏览服务器文件、下载、上传、删除 | file-tool |
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

## 动态库查找顺序

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
│   ├── dataset.py         # 数据集服务
│   ├── control.py         # 控制操作（直控/SBO）
│   ├── reports.py         # RCB 订阅（原生回调 -> Python 回调）
│   └── files.py           # MMS 文件服务（列目录/下载/上传/删除）
├── agent/                 # AI Agent（本分支新增）
│   ├── llm.py             # OpenAI 兼容 Chat Completions 客户端（纯 urllib）
│   ├── tools.py           # 工具 Schema + 执行器（含安全校验/人工确认）
│   └── assistant.py       # AgentSession：对话 + 工具调用循环
├── gui/                   # ttkbootstrap 界面层
│   ├── app.py             # 主窗口 + 连接管理 + 线程调度 + 主题切换
│   ├── widgets.py         # 自绘圆角按钮
│   └── tabs/              # 六个功能标签页（互不依赖，均只依赖 app 接口）
└── main.py                # 入口
```

## 技术说明

- 所有阻塞的 MMS 服务调用都在**工作线程**执行，报告回调发生在库内部线程，
  两者均经消息队列转发到主线程更新 UI，界面不卡顿
- LLM 请求与工具执行同样在工作线程，经队列回主线程渲染对话
- 读到的值自动按 MMS 类型转换（布尔/整数/浮点/字符串，结构体与数组递归展开为列表）
- 写值时自动识别输入：`true/false` → 布尔，整数/浮点 → 数值，其余 → 字符串
- 发送按钮等状态采用轮询式刷新，任何回调异常后都能自动恢复，不会永久置灰

## 已验证（对 libiec61850 自带示例服务器实测）

- 模型浏览（LD/LN/DO/DA）与读值 ✔
- 数据集读取（IED1LD1/LLN0.AnalogEvents）✔
- RCB 订阅收到实时报告 5 条 ✔
- SPCSO1 控制操作成功，stVal 变为 True ✔
- 文件服务：列目录 / 下载（内容比对一致）/ 上传 / 删除 ✔
- AI 工具：list_model(23 DO) / read_value / list_rcbs(10) / watch_reports(收到报告) ✔
- AI 遥控确认流程：operate_control 弹窗确认后执行成功 ✔
- AgentSession 工具调用循环（模拟 LLM 多轮）✔
- 获取模型列表（/models 端点解析）✔

> 提示：`server_example_files` 服务器要求运行目录下存在 `vmd-filestore/`
> 文件夹，否则文件目录服务会返回"类型不匹配"错误（IED_ERROR 22）。

> 注意：`ai_settings.json` 以**明文**保存 LLM 接口配置和 API Key，
> 请勿将其提交到版本库或共享给他人。


