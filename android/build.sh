#!/usr/bin/env bash
# Builds PrintWatch.apk with the plain Android build tools (no Gradle, no Google downloads).
# Debian/Ubuntu: sudo apt install aapt apksigner zipalign dalvik-exchange android-sdk-platform-23 default-jdk
set -euo pipefail
cd "$(dirname "$0")"
JAR=/usr/lib/android-sdk/platforms/android-23/android.jar
OUT=build
rm -rf "$OUT"; mkdir -p "$OUT/gen" "$OUT/obj"

aapt package -f -m -J "$OUT/gen" -M AndroidManifest.xml -S res -I "$JAR"
javac -nowarn -Xlint:-options -source 8 -target 8 -encoding UTF-8 -bootclasspath "$JAR" \
      -d "$OUT/obj" $(find src "$OUT/gen" -name '*.java')
dalvik-exchange --dex --output="$OUT/classes.dex" "$OUT/obj"
aapt package -f -M AndroidManifest.xml -S res -I "$JAR" -F "$OUT/unsigned.apk"
(cd "$OUT" && aapt add unsigned.apk classes.dex)
zipalign -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

# Your own signing key. Keep printwatch.keystore: updates must be signed with the same key.
if [[ ! -f printwatch.keystore ]]; then
  keytool -genkeypair -keystore printwatch.keystore -storepass printwatch -keypass printwatch \
          -alias printwatch -keyalg RSA -keysize 3072 -validity 18250 -dname "CN=PrintWatch"
fi
apksigner sign --ks printwatch.keystore --ks-pass pass:printwatch --ks-key-alias printwatch \
               --out PrintWatch.apk "$OUT/aligned.apk"
apksigner verify --print-certs PrintWatch.apk | head -3
ls -la PrintWatch.apk
