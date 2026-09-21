#!/bin/bash
# release/build_standalone_app.sh
#
# 配布用(自サイト/GitHub Releaseに置く用)の、単体で完結したAdvisor.appを
# ビルドする。エンドユーザー向けの setup.sh とは別物、メンテナ用ツール。
#
# setup.shが生成するAdvisor.appは"alias mode"(py2app -A)で、ビルドした
# そのMacの ~/claude-build/advisor_gui.py を都度読みに行く軽量な作り。
# これは同じMac上でしか動かないので配布には使えない。
#
# こちらは claude-agent.pl / models.txt をアプリ本体(Contents/Resources/)
# に同梱した"standalone"ビルドを作る。zipにしてどのMacに持って行っても、
# setup.shを一度も実行していなくても、ダブルクリックだけで動く
# (advisor_gui.py起動時のオンボーディング画面がAPIキー登録を担当する)。
#
# 実際に配布するOSと同じ機種の上でビルドすること(バイナリ互換性のため)。
#
# 使い方: bash release/build_standalone_app.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="0.1"
OUT_DIR="$SCRIPT_DIR/dist"
ICON_SRC="$SCRIPT_DIR/launcher/advisor.icns"

PY3="$(command -v python3 || true)"
[ -z "$PY3" ] && [ -x /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 ] \
  && PY3=/Library/Frameworks/Python.framework/Versions/3.10/bin/python3
if [ -z "$PY3" ]; then
  echo "python3 が見つかりません。" >&2
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Xcode Command Line Tools を導入しています(初回のみ・約190MB)..."
  touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  clt_label="$(softwareupdate -l 2>/dev/null | grep -o 'Command Line Tools[^,]*for Xcode-[0-9.]*' | tail -1)"
  [ -n "$clt_label" ] && softwareupdate -i "$clt_label" >/dev/null 2>&1
  rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  if ! xcode-select -p >/dev/null 2>&1; then
    echo "Command Line Toolsの導入に失敗しました。" >&2
    exit 1
  fi
fi

echo "py2app / pyobjc を導入しています..."
"$PY3" -m pip install --user --quiet py2app pyobjc-framework-Cocoa

BUILD_DIR="$SCRIPT_DIR/.standalone-app-build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp "$SCRIPT_DIR/gui/advisor_gui.py" "$BUILD_DIR/advisor_gui.py"

iconfile_opt=""
[ -f "$ICON_SRC" ] && iconfile_opt="\"iconfile\": \"$ICON_SRC\","

cat > "$BUILD_DIR/setup.py" << PYEOF
from setuptools import setup

APP = ["advisor_gui.py"]
# ("", [...]) は Contents/Resources/ 直下に置く指定。advisor_gui.py の
# _bundled_resource_dir() がここを見に行く。
DATA_FILES = [
    ("", ["$SCRIPT_DIR/agent/claude-agent.pl", "$SCRIPT_DIR/models.txt"]),
]
OPTIONS = {
    "argv_emulation": False,
    $iconfile_opt
    "plist": {
        "CFBundleName": "Advisor",
        "CFBundleDisplayName": "Advisor",
        "CFBundleIdentifier": "com.high-sierra-claude.advisor",
        "CFBundleVersion": "$VERSION",
        "CFBundleShortVersionString": "$VERSION",
        "NSHighResolutionCapable": True,
    },
}
setup(app=APP, data_files=DATA_FILES, options={"py2app": OPTIONS},
      setup_requires=["py2app"])
PYEOF

echo "standalone ビルド中(alias modeと違い実体をまるごとコピーするので、初回は数分かかります)..."
( cd "$BUILD_DIR" && rm -rf build dist && "$PY3" setup.py py2app )

if [ ! -d "$BUILD_DIR/dist/Advisor.app" ]; then
  echo "ビルドに失敗しました。$BUILD_DIR/build.log 等を確認してください。" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
rm -rf "$OUT_DIR/Advisor.app"
cp -R "$BUILD_DIR/dist/Advisor.app" "$OUT_DIR/Advisor.app"

ZIP_NAME="Advisor-v${VERSION}-standalone.zip"
( cd "$OUT_DIR" && rm -f "$ZIP_NAME" && zip -r -q "$ZIP_NAME" Advisor.app )

echo ""
echo "完成: $OUT_DIR/$ZIP_NAME"
du -sh "$OUT_DIR/Advisor.app" "$OUT_DIR/$ZIP_NAME"
