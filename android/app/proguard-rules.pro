# Add project specific ProGuard rules here.
-keepattributes Signature
-keepattributes *Annotation*

# Keep Gson model classes
-keep class com.gpxpoienricher.data.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
