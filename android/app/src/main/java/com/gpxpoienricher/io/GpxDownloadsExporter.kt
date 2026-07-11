package com.gpxpoienricher.io

import android.content.ContentResolver
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
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

    /** Trailing slash matches what MediaStore persists for [RELATIVE_PATH]. */
    private val downloadsRelativePath: String
        get() = "${Environment.DIRECTORY_DOWNLOADS}/$FOLDER_NAME/"

    /** Label for UI (not always a real absolute path on Android 10+). */
    fun displayPath(fileName: String): String = "Downloads/$FOLDER_NAME/$fileName"

    enum class ExportMode {
        /** Replace an existing Downloads entry or create [preferredName]. */
        OVERWRITE,
        /** Keep an existing Downloads entry unchanged (for reused track GPX files). */
        SKIP_IF_EXISTS,
    }

    /**
     * Copies [source] into public Downloads under [FOLDER_NAME].
     * @return [displayPath] for the name actually used.
     */
    fun exportFile(
        context: Context,
        source: File,
        preferredName: String = source.name,
        mode: ExportMode = ExportMode.OVERWRITE,
    ): String {
        require(source.isFile) { "Not a file: $source" }
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            exportViaMediaStore(context.contentResolver, source, preferredName, mode)
        } else {
            exportLegacy(source, preferredName, mode)
        }
    }

    private fun exportLegacy(source: File, preferredName: String, mode: ExportMode): String {
        val baseDir = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            FOLDER_NAME,
        )
        baseDir.mkdirs()
        val dest = File(baseDir, preferredName)
        if (dest.exists()) {
            if (mode == ExportMode.SKIP_IF_EXISTS) {
                return displayPath(dest.name)
            }
            FileInputStream(source).use { input -> dest.outputStream().use { input.copyTo(it) } }
            return displayPath(dest.name)
        }
        FileInputStream(source).use { input -> dest.outputStream().use { input.copyTo(it) } }
        return displayPath(dest.name)
    }

    private fun exportViaMediaStore(
        resolver: ContentResolver,
        source: File,
        preferredName: String,
        mode: ExportMode,
    ): String {
        findExistingEntry(resolver, preferredName)?.let { (uri, displayName) ->
            if (mode == ExportMode.SKIP_IF_EXISTS) {
                return displayPath(displayName)
            }
            copyToUri(resolver, uri, source)
            return displayPath(displayName)
        }
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
            copyToUri(resolver, uri, source)
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        } catch (e: Exception) {
            runCatching { resolver.delete(uri, null, null) }
            throw e
        }
        return displayPath(displayName)
    }

    private fun copyToUri(resolver: ContentResolver, uri: Uri, source: File) {
        resolver.openOutputStream(uri, "wt")!!.use { out ->
            FileInputStream(source).use { it.copyTo(out) }
        }
    }

    private fun pickUniqueDisplayName(resolver: ContentResolver, preferredName: String): String {
        if (findExistingEntry(resolver, preferredName) == null) return preferredName
        val stem = preferredName.substringBeforeLast('.', preferredName)
        val ext = if ('.' in preferredName) ".${preferredName.substringAfterLast('.')}" else ""
        for (n in 1..9999) {
            val candidate = "${stem}_$n$ext"
            if (findExistingEntry(resolver, candidate) == null) return candidate
        }
        return "${stem}_${System.currentTimeMillis()}$ext"
    }

    private fun findExistingEntry(resolver: ContentResolver, displayName: String): Pair<Uri, String>? {
        val projection = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
        )
        val selection =
            "${MediaStore.MediaColumns.DISPLAY_NAME} = ? AND ${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?"
        val args = arrayOf(displayName, "${downloadsRelativePath.trimEnd('/')}%")
        resolver.query(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            projection,
            selection,
            args,
            null,
        )?.use { cursor ->
            if (!cursor.moveToFirst()) return null
            val id = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns._ID))
            val name = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME))
            return ContentUris.withAppendedId(MediaStore.Downloads.EXTERNAL_CONTENT_URI, id) to name
        }
        return null
    }
}
