package com.gpxpoienricher.io

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns

/** Saved document permissions can expire or the document can be deleted. */
fun documentName(resolver: ContentResolver, uri: Uri): String? = try {
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
        val idx = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (it.moveToFirst()) {
            if (idx >= 0) it.getString(idx) ?: "Selected file" else "Selected file"
        } else null
    }
} catch (_: SecurityException) {
    null
} catch (_: IllegalArgumentException) {
    null
}
