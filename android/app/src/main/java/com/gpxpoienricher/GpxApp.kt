package com.gpxpoienricher

import android.app.Application
import com.chaquo.python.android.AndroidPlatform
import com.chaquo.python.Python
import com.google.android.gms.ads.MobileAds
import com.gpxpoienricher.monetization.PlayStoreMonetization
import java.io.File

class GpxApp : Application() {

    lateinit var monetization: PlayStoreMonetization
        private set
    private var adsInitialized = false

    @Synchronized
    fun initializeAdsIfNeeded() {
        if (adsInitialized) return
        adsInitialized = true
        MobileAds.initialize(this) {}
    }

    override fun onCreate() {
        super.onCreate()
        monetization = PlayStoreMonetization(this)
        monetization.start()

        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        extractProfiles()
    }

    companion object {
        private lateinit var app: GpxApp

        fun profilesDir(): File = File(app.filesDir, "profiles")

        /** Stable GPX scratch directory (same path across runs so reused tracks are detected). */
        fun gpxWorkDir(): File {
            val prefs = app.getSharedPreferences("gpx_work_dir", MODE_PRIVATE)
            prefs.getString("path", null)?.let { stored ->
                File(stored).takeIf { it.isDirectory }?.let { return it }
            }
            val dir = app.getExternalFilesDir("gpx") ?: File(app.filesDir, "gpx")
            dir.mkdirs()
            prefs.edit().putString("path", dir.absolutePath).apply()
            return dir
        }

        internal fun init(instance: GpxApp) {
            app = instance
        }

        /**
         * Ensures ``profiles/builtin`` (from assets) and ``profiles/user`` (custom) exist.
         * Legacy flat ``*.yaml`` files in the profiles root are moved into ``user/``.
         */
        @Synchronized
        fun extractProfiles(): File {
            val root = profilesDir()
            root.mkdirs()
            val builtin = File(root, "builtin").apply { mkdirs() }
            val user = File(root, "user").apply { mkdirs() }

            root.listFiles()?.forEach { f ->
                if (f.isFile && (f.name.endsWith(".yaml") || f.name.endsWith(".yml"))) {
                    val dest = File(user, f.name)
                    if (!dest.exists()) {
                        f.renameTo(dest)
                    } else {
                        f.delete()
                    }
                }
            }

            val names = app.assets.list("profiles").orEmpty()
                .filter { it.endsWith(".yaml") || it.endsWith(".yml") }.toSet()
            names.forEach { name ->
                val temporary = File(builtin, ".$name.tmp")
                try {
                    app.assets.open("profiles/$name").use { input ->
                        temporary.outputStream().use { input.copyTo(it) }
                    }
                    check(temporary.renameTo(File(builtin, name))) { "Could not install profile $name" }
                } finally {
                    temporary.delete()
                }
            }
            builtin.listFiles()?.filter {
                (it.name.endsWith(".yaml") || it.name.endsWith(".yml")) && it.name !in names
            }?.forEach { it.delete() }
            return root
        }
    }

    init {
        init(this)
    }
}
