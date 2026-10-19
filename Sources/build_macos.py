"""Rebuild the Apple Silicon app on this Mac.

The engine is shipped as readable Python plus its small vendored libraries.
This avoids a PyInstaller build step and keeps the source inspectable inside
the app bundle. The launcher uses the Mac's Python 3.9+ runtime.
"""
import os, shutil, subprocess
from pathlib import Path

root=Path(__file__).resolve().parent.parent
source=root/'Sources'
app=root/'iPod Drop.app';contents=app/'Contents'
(contents/'MacOS').mkdir(parents=True,exist_ok=True)
(contents/'Resources').mkdir(exist_ok=True)
shutil.copy2(source/'Info.plist',contents/'Info.plist')
subprocess.run(['swiftc','-parse-as-library','-swift-version','6','-O',str(source/'iPodDrop.swift'),'-o',str(contents/'MacOS/iPodDrop')],check=True)
engine=contents/'Resources/Engine'
if engine.exists():shutil.rmtree(engine)
engine.mkdir(parents=True)
shutil.copy2(source/'engine.py',engine/'engine.py')
shutil.copytree(source/'vendor/ipodsync',engine/'vendor/ipodsync')
shutil.copytree(source/'vendor/mutagen',engine/'vendor/mutagen')
launcher=engine/'ipod-engine'
launcher.write_text('''#!/bin/sh
DIR="$(cd "$(dirname "$0")" && pwd)"
for PY in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$PY" ] && "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    exec "$PY" "$DIR/engine.py"
  fi
done
osascript -e 'display alert "iPod Drop 需要 Python 3.9 或更新版本" message "请安装 Python 3，或从系统提示安装命令行工具后重试。" as critical'
exit 1
''',encoding='utf-8')
launcher.chmod(0o755)
shutil.copytree(root/'licenses',contents/'Resources/licenses',dirs_exist_ok=True)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
print(app)
