# 以撒 × 明日方舟：Windows 安装预览版

[**下载安装包**](https://github.com/aaahah845/isaac-arknights-bridge/releases/download/v0.4.10-preview.1/IsaacArknights-Windows-0.4.10-preview.zip) · [发布页与校验文件](https://github.com/aaahah845/isaac-arknights-bridge/releases/tag/v0.4.10-preview.1) · [视频简介文案](%E8%A7%86%E9%A2%91%E7%AE%80%E4%BB%8B.txt)

**三步开始：**先准备方舟 PC 官服 **2.7.91** 和 Steam《以撒：忏悔+》**v1.9.7.17/J460**，保持 Steam 登录；完整解压安装包，依次打开 **01、02** 并选择两款游戏的程序文件；安装完成后打开 **03**，以撒新开一局、方舟进入关卡即可联动。首次安装需联网，并预留约 **32 GB** 空间。

正常玩家请下载上面的完整安装包。GitHub 的 **Code → Download ZIP** 提供源码，源码包面向自行构建的开发者。

这是双游戏本地联动项目的安装预览版。安装包提供两个安装向导和统一启动入口，不包含游戏本体、官方账号数据或作者存档。基于已有官方客户端创建独立副本，生成新存档。需要 Windows 10/11 x64、Steam 登录和拥有相应游戏及 DLC。

## 使用

1. 完整解压安装包到长期保留的可写目录，例如 `D:\IsaacArknights`。
2. 打开 **01-安装方舟联动.exe**，选择国服 PC 客户端的 `Arknights.exe`，设置独立副本位置，完成安装。
3. 打开 **02-安装以撒联动.exe**，选择 Steam 以撒根目录的 `isaac-ng.exe`，设置独立副本位置，完成安装。已装支持版 REPENTOGON 会直接复制；未安装时会自动下载固定版本，并对副本应用官方启动器提供的兼容补丁。
4. 保持 Steam 登录，打开 **03-启动联动.exe**，等待启动完成。以撒新开一局，方舟进入关卡后即可联动。首次打开游戏可能需要自行处理游戏协议及窗口提示。

控制：WASD 移动，方向键射击，空格使用主动。F2 临时打开以撒控制台。方舟的鼠标操作仍由游戏处理。界面保留原版属性和左下角主动/充能，不显示常驻桥接标签。

安装器需要访问 GitHub 下载固定版本的本地服务和客户端适配组件，联网不畅会报错并保留日志。请保留完整解压目录，三个 exe 依赖旁边的 runtime、setup、payload、components；不能只复制 exe。安装后不要移动安装包或两个副本目录。

## 支持范围与空间

本预览版严格检查：方舟国服 PC **2.7.91**（Windows 资源 **26-10-29-15-35-15-96278206**）；Steam 以撒忏悔+ **v1.9.7.17 J460**（自动转换副本为 **J273 / REPENTOGON 1.1.3**），或者已装此支持版 REPENTOGON 的客户端。版本变更可能影响内存接口，不保证任意最新版本可用。自动转换只使用用户本地文件与官方公开的差分补丁；可执行文件、引擎 DLL 和转换后的主要资源均校验 SHA-256。只安装以撒基础版或未装相应 DLC 不足以运行此联动。

发布包复用玩家的安装文件，节省重新下载游戏的流量。安装采用完整独立副本，不使用可写硬链接/目录链接共享官方资源，因此磁盘仍需预留约 **28 GB 方舟副本 + 3 GB 以撒副本 + 1 GB 组件/余量**。以本地实际资源大小为准，复制前会检查磁盘空间。

以撒对部分中文路径的模组枚举有兼容问题，安装器会在 ProgramData/IsaacArknightsBridge 下创建一个指向所选**私有副本**的英文兼容入口；它不指向官方客户端，也不重复占用资源空间。配置和存档仍位于所选副本目录。删除副本后，可移除 install-state.json 中 runtimeDestination 指定的该兼容入口；只删除入口本身，不递归删除其他目录。

原客户端不打补丁；桥接仅注入副本。官方版仍从原启动器/Steam 进入。新存档不导入 Steam 进度或原账号。删除安装包前，先正常退出两个联动游戏；副本在外部目录时需另行删除。原版游戏不受影响。

## 故障与验证

安装日志：`installation.log`；启动日志：`launch.log`；具体游戏和桥接日志：`work` 目录。版本不匹配时不要强行跳过校验。默认使用本机 27042、27043、18731、8443 端口；旧版联动仍运行时请先退出。

这是安装预览版。已测试从官方文件安装方舟、从已装 REPENTOGON 的客户端复制安装，以及从**没有 REPENTOGON 的 Steam 文件副本**自动转换安装。已验证中文、空格和单引号路径。实际完成的验证和限制以随包 `validation.json` 为准；这不等于已在另一台全新 Windows 系统完成验证。游戏联动仍可能存在性能、Boss、多道具组合等问题。

## 组件和源码

自有桥接模板在 `payload/templates`，安装器源码在 `setup`。运行时按安装位置生成 `work` 内的配置与脚本，不依赖开发者盘符。固定上游版本及 SHA-256 在 `payload/manifest.json`。

服务端：[OpenBachelorS](https://github.com/pfyy/OpenBachelorS)，固定提交 `86099996610c3f3b5dc133bdf090e7c3848ee0fe`。PC 适配脚本：[OpenBachelorC](https://github.com/pfyy/OpenBachelorC)，固定提交 `9cf2bf92249ee008e28b74f8c54d3f0d55786737`。这些组件首次安装时从上游下载；本包不宣称拥有它们的再许可权。OpenBachelorC 的现成 native.js 上游部分源码为加密形式，不能声称本项目全部组件均可从可读源代码重新编译。

REPENTOGON：[官方安装说明](https://repentogon.com/install.html)。附带未修改的官方启动器及其 GPL 许可证和对应源码快照（licenses）。游戏程序及资源由用户自己的安装目录提供。Python、Qt、Frida 等依赖的许可证随运行时保留，详见 THIRD_PARTY_NOTICES.md。

本仓库包含安装器源码、自有桥接模板、构建脚本、依赖锁、固定组件清单、说明和验证报告；完整成品安装包放在 [Releases](https://github.com/aaahah845/isaac-arknights-bridge/releases)。本地生成的 games、work 服务端账号、profile、cache、日志和官方客户端不属于发布内容。

## 从源码打包

解压 GitHub 源码包，安装标准 CPython **3.14 x64**（含 pip），在源码根目录执行 `py -3.14 setup/build_portable.py --output D:/IA-dist`。脚本会按锁文件安装依赖、复制 Python 运行时，并使用 Windows 自带 .NET Framework C# 编译器生成三个入口。构建时无需安装两款游戏；玩家运行安装器时才选择本地游戏。构建需要联网下载 Python 依赖。

源码包中的 payload、components、licenses 也是构建输入，请完整保留。`setup/test_installer.py` 可用 `py -3.14 -m unittest discover -s setup -p test_installer.py` 运行。复现自己的联动运行应使用完整成品安装包，正常玩家无需安装 Python。
