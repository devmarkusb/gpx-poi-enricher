# R8 (minify + obfuscation) is enabled in build.gradle.kts for the release
# build type (Google Play "DEX code optimization" requirement).
#
# Coverage:
# - Chaquopy 16 auto-generates keep rules for any classes accessed from
#   Python. Our Python bridge (src/main/python/gpx_bridge.py) never imports
#   Java classes; Kotlin only calls named modules, which live outside the DEX.
# - AndroidX, play-services-ads, billing-ktx, and UMP ship their own consumer
#   rules.
# - Gson model classes and OkHttp are covered by the explicit rules below.

# Keep real line numbers in release stack traces so Play-deobfuscated crash
# reports point at actual source lines (retraced with mapping.txt).
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
-keepattributes Signature
-keepattributes *Annotation*

# Keep Gson model classes
-keep class com.gpxpoienricher.data.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
