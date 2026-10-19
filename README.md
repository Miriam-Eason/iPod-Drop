# iPod Drop

[简体中文](README.md) | [English](README.en.md)

一个不依赖 iTunes 的 iPod nano 6/7 歌曲导入与管理工具。

把 MP3 或整个歌曲文件夹拖进窗口，就能批量追加到 iPod；也可以打开“管理歌曲”，搜索、勾选并删除设备上的歌曲。删除只影响 iPod，电脑里的原 MP3 不会被改动。

当前版本：`0.2.0`。详细操作说明见 [使用说明.md](使用说明.md)。

## 功能

- **批量导入**：拖入多个 MP3 或整个文件夹，支持递归查找。
- **精确去重**：按文件 SHA-256 判断，重复歌曲自动跳过。
- **歌曲管理**：搜索歌名、歌手、专辑，多选后从 iPod 删除。
- **不依赖 iTunes**：直接更新 iPod 的 SQLite 曲库和签名后的 `iTunesCDB`。
- **自动备份**：每次实际导入或删除前，备份整套曲库索引。
- **事务回滚**：写入失败或断电留下未完成事务时，可以恢复到操作前。
- **保留原文件**：导入是复制，删除只移除设备上的音频，不会删除电脑源文件。
- **跨平台界面**：macOS 原生 SwiftUI 应用；Windows 使用本地浏览器界面。
- **Windows 驱动助手**：引导安装 Paragon HFS+ 官方 10 天试用版，也兼容已安装的 Paragon/MacDrive 卷。

## 支持范围

- 面向采用 **SQLite 曲库 + HashAB 签名** 的 iPod nano 6/7。
- 当前验证设备为 iPod nano 7：USB 产品编号 `0x1267`，固件 `1.0.4`。
- 仅支持普通、无 DRM 的 MP3；不会转换 FLAC、Apple Music 订阅下载或其他格式。
- 单首 MP3 需在 iPod 可接受的参数范围内（采样率不超过 48 kHz、码率不超过 320 kbps）。
- 导入时请关闭 Finder、音乐或 iTunes 针对该设备的同步；Apple 后续执行整库同步仍可能覆盖手动改动。

## 快速开始

### macOS

1. 打开 `iPod Drop.app`，连接 iPod。
2. 把 MP3 或文件夹拖进窗口，或点“选择歌曲…”。
3. 需要删除歌曲时，点“管理歌曲”，搜索并勾选后删除。
4. 完成后点“安全弹出”。

应用使用 Mac 自带或 Homebrew 的 Python 3.9 及以上版本作为引擎运行时。当前构建的最低系统版本是 macOS 26.0；如果 Gatekeeper 提示未公证，可在确认来源后使用“仍要打开”。

### Windows x64

1. 完整解压 `iPod-Drop-Windows-x64.zip` 到有写权限的目录。
2. 双击 `Start iPod Drop.cmd`，浏览器会打开工具页面。
3. 连接 iPod，点“刷新设备”，然后拖入歌曲。
4. 删除歌曲使用“管理歌曲”标签页。

包内已带 Python 3.13 x64 运行时，不需要另外安装 Python。不要直接在压缩包里运行。

### Windows 32 位

1. 完整解压 `iPod-Drop-Windows32-x86.zip`。
2. 双击 `Start iPod Drop.cmd`。
3. 首次启动会从 python.org 下载官方 Python 3.13（找不到时尝试 3.12）32 位嵌入式运行时，保存到包内 `runtime32` 目录。需要联网一次，并会检查 PE 架构。
4. 不能联网时，可先安装官方 32 位 Python 3.9 或更新版本；启动脚本会通过 `py -3-32` 使用它。

32 位包也能在 64 位 Windows 的 WoW64 环境运行。

### Windows HFS+ 驱动

这台 iPod 当前是 HFS+（Mac OS 扩展）格式，Windows 原生不能读写 HFS+，需要额外的文件系统驱动。工具里有“Windows 驱动”页，也可以直接双击 `安装 Windows HFS+ 驱动.cmd`。

驱动助手现在会：

1. 请求管理员权限；
2. 从 Paragon 官方地址下载 `hfs14_win_trial.msi`；
3. 校验 SHA-256（`b229a05dac3e49e36e86ecf8e7c5c4926e5d8ecc76505162eacce86642e4d3bd`）；
4. 调用 `msiexec` 安装 10 天试用版。

如果之前用 winget 装过正式版，打开后马上提示“激活”，先在“设置 → 应用”卸载它，再安装试用版。试用期结束后需要向 Paragon 购买授权（官方页面价格约 20 美元，具体以官网为准）。

可替代方案：

- 在 macOS 上使用本工具，零成本且最稳定。
- Linux 启动盘：Linux 内核自带 `hfsplus` 驱动，可读写 HFS+；适合愿意重启进 Linux 的用户，写入前应先备份。
- MacDrive：另一款付费 HFS+ 驱动，购买前确认支持你的 Windows 位数。
- HFSExplorer、7-Zip、Boot Camp HFS+ 驱动等免费工具大多只能读，不能导入或删除。
- 把 iPod 转成 FAT32 可以让 Windows 原生读写，但会清空设备，必须先完整备份并用 iTunes 做一次 Windows 格式恢复。

Paragon 官方试用安装包：[hfs14_win_trial.msi](https://dl.paragon-software.com/demo/hfs14_win_trial.msi)

## 删除与安全

删除会同步处理：

- 音频文件；
- `Library.itdb`、`Locations.itdb`、`Dynamic.itdb`、`Extras.itdb`；
- 播放统计、歌单条目和专辑/歌手/流派计数；
- 签名后的 `iTunesCDB`。

删除前会把整套曲库索引和即将删除的音频移入事务目录，全部校验通过后才提交。失败时会恢复数据库和音频；断电留下的未完成事务可在工具里点“恢复上次曲库”。

电脑上的源 MP3 始终保留。曲库备份本身不是全部音频的额外备份，重要歌曲请另外保留源文件。

## 备份与恢复

- macOS：`~/Library/Application Support/iPod Drop/Backups/<设备标识>/<时间>/`
- Windows：`%LOCALAPPDATA%\iPod Drop\Backups\<设备标识>\<时间>\`

“查看备份”会打开备份目录。备份暂不自动清理。

## 从源码构建

### macOS

需要 Swift 6、Xcode Command Line Tools 和 Python 3.9+：

```bash
python3 Sources/build_macos.py
```

输出为 `iPod Drop.app`，脚本会复制引擎、随包的 Mutagen/ipodsync 库并做临时签名。

### Windows 包

Windows 包由 `app/`、`runtime/` 和启动脚本组成。详细目录和运行时配置见 [packaging/README.md](packaging/README.md)。

- x64：使用 Python 3.13 embeddable **amd64** 运行时。
- 32 位：使用 [packaging/windows32](packaging/windows32) 中的首次启动下载器，或预装 32 位 Python。

`Sources/engine.py`、`Sources/server.py` 和 `Sources/windows.html` 是纯 Python/HTML，不依赖编译扩展。

## 项目结构

```text
Sources/
  engine.py              iPod 曲库、CDB、签名和事务逻辑
  server.py             Windows 本地 Web 服务
  windows.html          Windows 界面
  iPodDrop.swift        macOS SwiftUI 界面
  build_macos.py        macOS 构建脚本
  drivers/              Windows HFS+ 驱动助手
  vendor/               ipodsync 与 Mutagen
packaging/
  windows64/            x64 启动脚本和 _pth 模板
  windows32/            32 位运行时准备脚本
licenses/               第三方许可
validation/             测试与验证记录
使用说明.md              面向用户的详细说明
```

## 验证状态

已在 2026-10-19 完成：

- 在连接设备的完整临时副本上删除 2 首：38 → 36，其余音频 SHA-256 不变，SQLite、歌单计数和 `iTunesCDB` 签名均通过。
- 注入安装失败后，曲库和全部音频恢复到操作前。
- 模拟断电后重新执行 `recover` 成功。
- 导入后再删除测试曲通过。
- macOS 新版界面启动验证：识别 38 首歌曲，“管理歌曲”列表、搜索和勾选正常。
- Windows 引擎和页面脚本通过 Python/JavaScript 语法检查。

尚未完成：

- 真实 iPod 上的播放验证。
- 真实 Windows 机器上的 HFS+ 驱动和文件锁验证。
- 真实 32 位 Windows 启动验证。

详细记录见 [validation](validation)。

## 已知限制

- 只面向 iPod nano 6/7 的 SQLite/HashAB 曲库，不适用于更老的 iTunesDB 设备。
- 新增歌曲暂不写入封面；已有封面数据保留。
- 同一 MP3 改过标签后字节不同，会被视为另一个文件。
- 曲库写入直接操作设备文件系统；操作时不要同时运行 iTunes/音乐同步。
- macOS 应用是本地临时签名，没有 Apple 公证。

## 许可

本项目新增代码采用 GPL-2.0-or-later。第三方组件保留原许可：

- [ipodsync](https://github.com/buldiei/ipodsync)：MIT
- [dstaley/hashab](https://github.com/dstaley/hashab)：Unlicense
- [PodBox](https://github.com/MilanMarocchi/podbox)：MIT
- [Mutagen](https://mutagen.readthedocs.io/)：GPL-2.0-or-later

完整文本见 [LICENSE.txt](LICENSE.txt) 和 [licenses](licenses)。
