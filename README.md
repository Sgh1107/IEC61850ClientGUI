# IEC 61850 客户端 GUI 工具

基于 Python + ttkbootstrap 的 IEC 61850 客户端图形界面，通过 **ctypes 链接 libiec61850 动态库**（`iec61850.dll` / `libiec61850.so`）实现，不依赖项目源码编译。

## 功能（对应 examples 中各客户端示例）

| 标签页 | 功能 | 对应示例 |
| --- | --- | --- |
| 📂 数据浏览 | 树形浏览服务器模型（LD→LN→DO→DA 懒加载），读/写任意数据属性 | client_example1、example_array |
| 📋 数据集 | 读取数据集成员及实时值，支持单成员/整组写值 | client_example4 |
| 🎛 控制操作 | 直控 / SBO（先选择后操作）、操作来源、联锁/同期校验、操作日志 | client_example_control |
| 📡 报告订阅 | 扫描 RCB（BRCB/URCB）、订阅报告、总召(GI)、实时事件表格 | client_example_reporting |
| 🗃 文件服务 | 浏览服务器文件（双击进子目录）、下载、上传、删除 | file-tool |

## 运行

```bash
pip install ttkbootstrap

python main.py [服务器IP] [端口]
# 例: python main.py 192.168.31.57 102
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
│   ├── connection.py      # 连接 + 模型浏览 + 读/写
│   ├── dataset.py         # 数据集服务
│   ├── control.py         # 控制操作（直控/SBO）
│   ├── reports.py         # RCB 订阅（原生回调 -> Python 回调）
│   └── files.py           # MMS 文件服务（列目录/下载/上传/删除）
├── gui/                   # ttkbootstrap 界面层
│   ├── app.py             # 主窗口 + 连接管理 + 线程调度
│   └── tabs/              # 四个功能标签页（互不依赖，均只依赖 app 接口）
└── main.py                # 入口
```

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

