package com.gpxpoienricher.service

import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

const val USER_AGENT = "gpx-poi-enricher-android/1.0 (https://github.com/devmarkusb/gpx-poi-enricher)"

val sharedHttpClient: OkHttpClient by lazy {
    OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(240, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()
}
