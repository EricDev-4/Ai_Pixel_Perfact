#!/bin/sh
# Builds tools/build/Sprite Player.app from main.swift + ../sprite-player.html. Rerun after editing either.
set -eu
cd "$(dirname "$0")"
APP="../build/Sprite Player.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 main.swift -o "$APP/Contents/MacOS/SpritePlayer"
cp ../sprite-player.html "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>SpritePlayer</string>
  <key>CFBundleIdentifier</key><string>local.auto-pixelart.sprite-player</string>
  <key>CFBundleName</key><string>Sprite Player</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>CFBundleDocumentTypes</key><array><dict>
    <key>CFBundleTypeName</key><string>Image</string>
    <key>CFBundleTypeRole</key><string>Viewer</string>
    <key>LSHandlerRank</key><string>Alternate</string>
    <key>LSItemContentTypes</key><array>
      <string>public.png</string><string>com.compuserve.gif</string><string>org.webmproject.webp</string>
    </array>
  </dict></array>
</dict></plist>
EOF
codesign --force -s - "$APP"
# register with Launch Services so Dock drop and Open With know the app
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
echo "built: $(cd "$(dirname "$APP")" && pwd)/Sprite Player.app"
