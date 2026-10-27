package com.gpxpoienricher.audit

import android.app.Application
import androidx.test.runner.AndroidJUnitRunner
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.gpxpoienricher.GpxApp

/** Bootstrap real Python without opening billing or advertising services. */
class AuditTestRunner : AndroidJUnitRunner() {
    override fun callApplicationOnCreate(app: Application) {
        check(app is GpxApp && app.packageName.endsWith(".audit")) {
            "Audit tests require the isolated audit application variant"
        }
        // GpxApp's constructor registers the filesystem context. Its production onCreate
        // starts billing, so this headless runner deliberately bootstraps only Python.
        if (!Python.isStarted()) Python.start(AndroidPlatform(app))
        GpxApp.extractProfiles()
    }
}
