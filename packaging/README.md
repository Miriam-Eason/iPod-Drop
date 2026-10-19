# Windows 打包说明

Windows 版由三部分组成：

```text
iPod Drop Windows/
  app/
    engine.py
    server.py
    windows.html
    drivers/install-hfs-driver.ps1
    vendor/{ipodsync,mutagen}
  runtime/                 Python embeddable（x64 包自带）
  Start iPod Drop.cmd
  licenses/
  使用说明.md
```

## x64 包

1. 从 python.org 下载对应的 `python-3.13.x-embed-amd64.zip`。
2. 解压到 `runtime/`。
3. 把 `packaging/windows64/python313._pth` 复制到 `runtime/python313._pth`。它应包含：

   ```text
   python313.zip
   .
   ../app
   ../app/vendor
   ```

4. 把 `Sources/engine.py`、`Sources/server.py`、`Sources/windows.html` 复制到 `app/`。
5. 把 `Sources/drivers/` 复制到 `app/drivers/`。
6. 把 `Sources/vendor/ipodsync` 和 `Sources/vendor/mutagen` 复制到 `app/vendor/`。
7. 复制 `packaging/windows64/Start iPod Drop.cmd` 到包根目录。
8. 复制 `licenses/` 和 `使用说明.md`。

运行 `Start iPod Drop.cmd` 后，`server.py` 只监听 `127.0.0.1` 的随机端口，并打开本机浏览器。

## 32 位包

32 位包不内置运行时，使用 [windows32](windows32) 中的启动脚本：

- `Start iPod Drop.cmd`：优先使用 `runtime32\pythonw.exe`，否则调用 `py -3-32` 或系统 `pythonw`。
- `prepare 32-bit runtime.cmd`：调用 PowerShell 准备运行时。
- `prepare-runtime32.ps1`：从 python.org 下载官方 win32 embeddable，校验 PE 架构（`IMAGE_FILE_MACHINE_I386`，`0x014c`），再写入 `_pth`。

`app/` 内容与 x64 包完全相同；`app/vendor` 只包含纯 Python 模块，没有 64 位编译扩展。

## 运行时版本

当前发布包使用 Python 3.13.13 x64。32 位准备脚本优先尝试 3.13.13，找不到时依次尝试 3.13.12–3.13.7 和 3.12.11–3.12.7。

## 驱动助手

`app/drivers/install-hfs-driver.ps1` 会下载并校验 Paragon 官方 trial MSI，再调用 `msiexec`。如果目标机器已装有正式版并提示激活，应先卸载旧版本。
