#!/bin/bash
# 编译「刷课助手.app」。用法: gui/build_app.sh [输出路径]
# 默认输出到项目上一级目录。应用通过 Info.plist 里记录的路径找到本项目，移动项目后需要重新运行本脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(dirname "$ROOT")/刷课助手.app}"
BUILD="$ROOT/gui/build"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "找不到 $PY，请先在项目目录执行: uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt" >&2
  exit 1
fi

rm -rf "$BUILD"
mkdir -p "$BUILD"

echo "编译外壳程序…"
swiftc -O -o "$BUILD/ShuaKe" "$ROOT/gui/mac/main.swift" -framework Cocoa -framework WebKit

echo "生成图标…"
"$PY" "$ROOT/gui/mac/make_icon.py" "$BUILD/AppIcon.iconset"
iconutil -c icns "$BUILD/AppIcon.iconset" -o "$BUILD/AppIcon.icns"

echo "打包到 $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/Contents/MacOS" "$OUT/Contents/Resources"
cp "$BUILD/ShuaKe" "$OUT/Contents/MacOS/ShuaKe"
cp "$BUILD/AppIcon.icns" "$OUT/Contents/Resources/AppIcon.icns"

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
PROJECT_XML="$(printf '%s' "$ROOT" | xml_escape)"

cat > "$OUT/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>刷课助手</string>
  <key>CFBundleDisplayName</key><string>刷课助手</string>
  <key>CFBundleIdentifier</key><string>local.chaoxing.shuake</string>
  <key>CFBundleExecutable</key><string>ShuaKe</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>基于 Samueli924/chaoxing（GPL-3.0）</string>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>CXProjectPath</key><string>$PROJECT_XML</string>
</dict>
</plist>
PLIST

codesign --force --deep -s - "$OUT" >/dev/null 2>&1 || echo "（签名失败，不影响本机使用）"
touch "$OUT"
echo "完成：$OUT"
