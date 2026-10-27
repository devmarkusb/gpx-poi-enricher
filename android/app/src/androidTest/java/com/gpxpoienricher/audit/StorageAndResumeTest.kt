package com.gpxpoienricher.audit

import android.Manifest
import android.app.Application
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Environment
import android.os.SystemClock
import android.provider.MediaStore
import androidx.lifecycle.LiveData
import androidx.lifecycle.Observer
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.gpxpoienricher.GpxApp
import com.gpxpoienricher.io.GpxDownloadsExporter
import com.gpxpoienricher.ui.enricher.EnricherViewModel
import java.io.ByteArrayInputStream
import java.io.File
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 29)
class StorageAndResumeTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var context: Context
    private lateinit var pythonGlobals: PyObject
    private lateinit var profileId: String
    private val documents = mutableListOf<Uri>()
    private val stores = mutableListOf<ViewModelStore>()
    private val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
    private val gpxNamespace = "http://www.topografix.com/GPX/1/1"

    @Before
    fun setUp() {
        context = instrumentation.targetContext
        assertEquals(PackageManager.PERMISSION_DENIED, context.checkSelfPermission(Manifest.permission.INTERNET))
        profileId = "audit_${UUID.randomUUID().toString().replace("-", "")}"
        val python = Python.getInstance()
        python.getModule("gpx_bridge").callAttr(
            "save_profile_yaml", GpxApp.profilesDir().absolutePath,
            """
                id: $profileId
                description: Device audit
                tags: [{key: tourism, value: museum}]
                terms: {}
                defaults:
                  max_km: 1
                  sample_km: 0.001
                  batch_size: 1
                  retries: 0
                  early_cancel_if_no_pois: false
            """.trimIndent(),
        )
        pythonGlobals = python.getModule("builtins").callAttr("dict")
        executePython(
            """
                import threading
                from unittest.mock import patch
                import gpx_poi_enricher.enricher as engine
                import gpx_bridge as bridge
                query_calls = 0
                interrupt_after_first = False
                allow_resume = False
                block_queries = False
                entered_query = threading.Event()
                release_query = threading.Event()
                def query(*args, **kwargs):
                    global query_calls
                    query_calls += 1
                    if block_queries:
                        entered_query.set()
                        if not release_query.wait(20):
                            raise RuntimeError('Timed out waiting for test release')
                    if interrupt_after_first and not allow_resume and query_calls == 2:
                        raise RuntimeError('Offline test interruption')
                    if allow_resume:
                        return {'elements': []}
                    return {'elements': [{'type': 'node', 'id': 7, 'lat': 0.001, 'lon': 0.0,
                                          'tags': {'name': 'Device POI'}}]}
                patches = [
                    patch.object(engine, 'detect_country_segments', lambda pts, *a, **k: {'EN': pts}),
                    patch.object(engine, 'query_overpass', query),
                    patch.object(engine.time, 'sleep', lambda seconds: None),
                ]
                for item in patches:
                    item.start()
            """.trimIndent(),
        )
    }

    @After
    fun tearDown() {
        if (::pythonGlobals.isInitialized) executePython("release_query.set()")
        onMain { stores.forEach { it.clear() } }
        if (::pythonGlobals.isInitialized) executePython("for item in reversed(patches): item.stop()")
        documents.forEach { runCatching { context.contentResolver.delete(it, null, null) } }
        if (::profileId.isInitialized) {
            Python.getInstance().getModule("gpx_bridge").callAttr(
                "delete_profile", GpxApp.profilesDir().absolutePath, profileId,
            )
            GpxApp.gpxWorkDir().listFiles()?.filter { profileId in it.name }?.forEach { it.delete() }
        }
    }

    @Test
    fun restoringSelectionsPreservesResumeAndUsesCopiedInput() {
        executePython("interrupt_after_first = True")
        val source = document("source", trackGpx())
        val previousOutput = "previous output ".repeat(100)
        val output = document("output", previousOutput)
        val model = newModel()
        onMain {
            model.setInputFile(source)
            model.setOutputFile(output)
            model.run(profileIndex(model), null, 0.001, false, "")
        }
        awaitValue(model.canResume) { it == true }
        awaitValue(model.isRunning) { it == false }
        assertEquals(previousOutput, read(output))
        onMain {
            model.setInputFile(source)
            model.setOutputFile(output)
        }
        assertEquals(true, model.canResume.value)
        context.contentResolver.delete(source, null, null)
        executePython("allow_resume = True")
        onMain { model.run(profileIndex(model), null, 0.001, false, "") }
        awaitValue(model.isRunning) { it == false }
        assertEquals(false, model.canResume.value)
        val bytes = read(output).toByteArray()
        val factory = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        val root = factory.newDocumentBuilder().parse(ByteArrayInputStream(bytes))
        assertEquals(0, root.getElementsByTagNameNS(gpxNamespace, "trk").length)
        assertEquals(1, root.getElementsByTagNameNS(gpxNamespace, "wpt").length)
        assertEquals("Device POI", root.getElementsByTagNameNS(gpxNamespace, "name").item(0).textContent)
        assertFalse(GpxApp.gpxWorkDir().listFiles().orEmpty().any { profileId in it.name })
    }

    @Test
    fun cancellingQueuedSearchDoesNotCancelActiveSearch() {
        executePython("block_queries = True")
        val active = newModel()
        val queued = newModel()
        val activeOutput = document("active", "old active")
        val queuedOutput = document("queued", "old queued")
        onMain {
            active.setOutputFile(activeOutput)
            queued.setOutputFile(queuedOutput)
            active.run(profileIndex(active), null, null, true, "0,0")
        }
        awaitPython("entered_query.is_set()")
        onMain { queued.run(profileIndex(queued), null, null, true, "1,1") }
        awaitPython("len(bridge._operation_events) == 2")
        onMain { queued.cancel() }
        awaitPython("any(event.is_set() for event in bridge._operation_events.values())")
        executePython("assert not bridge._active_cancel_event.is_set(); release_query.set()")
        awaitValue(active.isRunning) { it == false }
        awaitValue(queued.isRunning) { it == false }
        assertTrue(read(activeOutput).contains("Device POI"))
        assertEquals("old queued", read(queuedOutput))
        executePython("assert query_calls == 1")
    }

    @Test
    fun sameNamedDocumentsDoNotOverwriteAnInterruptedSearch() {
        executePython("interrupt_after_first = True")
        val name = "same-name-${UUID.randomUUID()}.gpx"
        val firstSource = document(name, trackGpx(), "${Environment.DIRECTORY_DOWNLOADS}/GpxPoiAudit/first/", false)
        val secondSource = document(name, trackGpx(), "${Environment.DIRECTORY_DOWNLOADS}/GpxPoiAudit/second/", false)
        val firstOutput = document("first-output", "first sentinel")
        val secondOutput = document("second-output", "second sentinel")
        val first = newModel()
        val second = newModel()
        onMain {
            first.setInputFile(firstSource)
            first.setOutputFile(firstOutput)
            first.run(profileIndex(first), null, 0.001, false, "")
        }
        awaitValue(first.canResume) { it == true }
        awaitValue(first.isRunning) { it == false }
        executePython("allow_resume = True")
        onMain {
            second.setInputFile(secondSource)
            second.setOutputFile(secondOutput)
            second.run(profileIndex(second), null, 0.001, false, "")
        }
        awaitValue(second.isRunning) { it == false }
        assertTrue(read(secondOutput).contains("<gpx"))
        onMain { first.run(profileIndex(first), null, 0.001, false, "") }
        awaitValue(first.isRunning) { it == false }
        assertEquals("The second search destroyed the first search's resumable work", false, first.canResume.value)
        assertTrue(read(firstOutput).contains("Device POI"))
    }

    @Test
    fun exporterMatchesExactFolderAndTruncatesOverwrites() {
        val name = "audit-${UUID.randomUUID()}.gpx"
        val sibling = document(name, "sibling sentinel", "${Environment.DIRECTORY_DOWNLOADS}/GpxPoiEnricherBackup/", false)
        val source = File.createTempFile("audit-export", ".gpx", context.cacheDir)
        try {
            source.writeText("long initial output ".repeat(100))
            GpxDownloadsExporter.exportFile(context, source, name)
            val exported = findExport(name)
            documents.add(exported)
            assertEquals(source.readText(), read(exported))
            source.writeText("short")
            GpxDownloadsExporter.exportFile(context, source, name)
            assertEquals("short", read(exported))
            source.writeText("replacement")
            GpxDownloadsExporter.exportFile(context, source, name, GpxDownloadsExporter.ExportMode.SKIP_IF_EXISTS)
            assertEquals("short", read(exported))
            assertEquals("sibling sentinel", read(sibling))
            assertEquals(exported, findExport(name))
        } finally {
            source.delete()
        }
    }

    @Test
    fun deletedDocumentsAreNotRestoredIntoANewModel() {
        val uri = document("deleted", trackGpx())
        context.contentResolver.delete(uri, null, null)
        val model = newModel()
        onMain { model.setInputFile(uri); model.setOutputFile(uri) }
        assertNull(model.inputUri.value)
        assertNull(model.outputUri.value)
    }

    private fun newModel(): EnricherViewModel {
        val store = ViewModelStore().also { stores.add(it) }
        lateinit var model: EnricherViewModel
        onMain {
            val factory = ViewModelProvider.AndroidViewModelFactory.getInstance(context.applicationContext as Application)
            model = ViewModelProvider(store, factory)[EnricherViewModel::class.java]
        }
        awaitValue(model.profiles) { profiles -> profiles?.any { it.id == profileId } == true }
        return model
    }

    private fun profileIndex(model: EnricherViewModel): Int =
        model.profiles.value.orEmpty().indexOfFirst { it.id == profileId }.also { assertTrue(it >= 0) }

    private fun onMain(action: () -> Unit) = instrumentation.runOnMainSync(action)

    private fun <T> awaitValue(data: LiveData<T>, predicate: (T?) -> Boolean) {
        val ready = CountDownLatch(1)
        val observer = Observer<T> { if (predicate(it)) ready.countDown() }
        onMain { data.observeForever(observer) }
        try {
            assertTrue("Timed out waiting for LiveData", ready.await(25, TimeUnit.SECONDS))
        } finally {
            onMain { data.removeObserver(observer) }
        }
    }

    private fun executePython(code: String) {
        Python.getInstance().getModule("builtins").callAttr("exec", code, pythonGlobals)
    }

    private fun awaitPython(expression: String) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (!Python.getInstance().getModule("builtins").callAttr("eval", expression, pythonGlobals).toBoolean()) {
            check(SystemClock.elapsedRealtime() < deadline) { "Timed out waiting for Python state" }
            SystemClock.sleep(10)
        }
    }

    private fun document(label: String, content: String, folder: String = "${Environment.DIRECTORY_DOWNLOADS}/GpxPoiAudit/", unique: Boolean = true): Uri {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, if (unique) "audit-$label-${UUID.randomUUID()}.gpx" else label)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/gpx+xml")
            put(MediaStore.MediaColumns.RELATIVE_PATH, folder)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = requireNotNull(context.contentResolver.insert(collection, values))
        documents.add(uri)
        context.contentResolver.openOutputStream(uri, "wt")!!.use { it.write(content.toByteArray()) }
        values.clear()
        values.put(MediaStore.MediaColumns.IS_PENDING, 0)
        context.contentResolver.update(uri, values, null, null)
        return uri
    }

    private fun read(uri: Uri): String = context.contentResolver.openInputStream(uri)!!.use {
        it.readBytes().toString(Charsets.UTF_8)
    }

    private fun findExport(name: String): Uri {
        val columns = arrayOf(MediaStore.MediaColumns._ID, MediaStore.MediaColumns.IS_PENDING)
        val selection = "${MediaStore.MediaColumns.DISPLAY_NAME} = ? AND ${MediaStore.MediaColumns.RELATIVE_PATH} = ?"
        val args = arrayOf(name, "${Environment.DIRECTORY_DOWNLOADS}/${GpxDownloadsExporter.FOLDER_NAME}/")
        return context.contentResolver.query(collection, columns, selection, args, null)!!.use {
            assertEquals(1, it.count)
            assertTrue(it.moveToFirst())
            assertEquals(0, it.getInt(1))
            ContentUris.withAppendedId(collection, it.getLong(0))
        }
    }

    private fun trackGpx(): String =
        """<gpx xmlns="$gpxNamespace" version="1.1" creator="device-test"><trk><trkseg><trkpt lat="0" lon="0"/><trkpt lat="0" lon="0.1"/><trkpt lat="0" lon="0.2"/></trkseg></trk></gpx>"""
}
