package com.gpxpoienricher.io

import android.content.ContentResolver
import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.FileInputStream

/**
 * Copies GPX outputs into a user-visible folder under public Downloads
 * ([FOLDER_NAME]), using [MediaStore] on API 29+ and direct files on API 26–28
 * (requires [android.Manifest.permission.WRITE_EXTERNAL_STORAGE]).
 */
object GpxDownloadsExporter {

    const val FOLDER_NAME = "GpxPoiEnricher"

    private const val MIME_GPX = "application/gpx+xml"

    private val downloadsRelativePath: String
        get() = "${Environment.DIRECTORY_DOWNLOADS}/$FOLDER_NAME"

    /** Label for UI (not always a real absolute path on Android 10+). */
    fun displayPath(fileName: String): String = "Downloads/$FOLDER_NAME/$fileName"

    /**
     * Copies [source] into public Downloads under [FOLDER_NAME].
     * @return [displayPath] for the name actually used (may differ if de-duplicated).
     */
    fun exportFile(context: Context, source: File, preferredName: String = source.name): String {
        require(source.isFile) { "Not a file: $source" }
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            exportViaMediaStore(context.contentResolver, source, preferredName)
        } else {
            exportLegacy(source, preferredName)
        }
    }

    private fun exportLegacy(source: File, preferredName: String): String {
        val baseDir = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            FOLDER_NAME,
        )
        baseDir.mkdirs()
        var dest = File(baseDir, preferredName)
        var n = 1
        while (dest.exists()) {
            val stem = preferredName.substringBeforeLast('.', preferredName)
            val ext = if ('.' in preferredName) ".${preferredName.substringAfterLast('.')}" else ""
            dest = File(baseDir, "${stem}_$n$ext")
            n++
        }
        FileInputStream(source).use { input -> dest.outputStream().use { input.copyTo(it) } }
        return displayPath(dest.name)
    }

    private fun exportViaMediaStore(resolver: ContentResolver, source: File, preferredName: String): String {
        val displayName = pickUniqueDisplayName(resolver, preferredName)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, MIME_GPX)
            put(MediaStore.MediaColumns.RELATIVE_PATH, downloadsRelativePath)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val uri = resolver.insert(collection, values)
            ?: error("MediaStore.insert returned null for $displayName")
        try {
            resolver.openOutputStream(uri)!!.use { out ->
                FileInputStream(source).use { it.copyTo(out) }
            }
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (e: Exception) {
            runCatching { resolver.delete(uri, null, null) }
            throw e
        }
        return displayPath(displayName)
    }

    private fun pickUniqueDisplayName(resolver: ContentResolver, preferredName: String): String {
        if (!existsInDownloads(resolver, preferredName)) return preferredName
        val stem = preferredName.substringBeforeLast('.', preferredName)
        val ext = if ('.' in preferredName) ".${preferredName.substringAfterLast('.')}" else ""
        for (n in 1..9999) {
            val candidate = "${stem}_$n$ext"
            if (!existsInDownloads(resolver, candidate)) return candidate
        }
        return "${stem}_${System.currentTimeMillis()}$ext"
    }

    private fun existsInDownloads(resolver: ContentResolver, displayName: String): Boolean {
        val projection = arrayOf(MediaStore.MediaColumns._ID)
        val selection = "${MediaStore.MediaColumns.DISPLAY_NAME} = ? AND ${MediaStore.MediaColumns.RELATIVE_PATH} = ?"
        val args = arrayOf(displayName, downloadsRelativePath)
        return resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            projection,
            selection,
            args,
            null,
        )?.use { it.moveToFirst() } == true
    }
}
