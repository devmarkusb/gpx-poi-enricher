package com.gpxpoienricher

import android.app.Application
import com.chaquo.python.android.AndroidPlatform
import com.chaquo.python.Python
import java.io.File

class GpxApp : Application() {

    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        extractProfiles()
    }

    companion object {
        private lateinit var app: GpxApp

        fun profilesDir(): File = File(app.filesDir, "profiles")

        internal fun init(instance: GpxApp) { app = instance }

        fun extractProfiles(): File {
            val dir = profilesDir()
            dir.mkdirs()
            app.assets.list("profiles")?.forEach { name ->
                File(dir, name).outputStream().use { out ->
                    app.assets.open("profiles/$name").copyTo(out)
                }
            }
            return dir
        }
    }

    init { init(this) }
}
