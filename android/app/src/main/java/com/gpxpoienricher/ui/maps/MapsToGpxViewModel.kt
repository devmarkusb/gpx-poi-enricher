package com.gpxpoienricher.ui.maps

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import com.gpxpoienricher.LogCallback
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MapsToGpxViewModel(app: Application) : AndroidViewModel(app) {

    companion object {
        const val DEFAULT_TRACK_NAME = "Route"
        const val DEFAULT_OUTPUT_BASENAME = "route.gpx"
    }

    private val _outputUri = MutableLiveData<Uri?>()
    val outputUri: LiveData<Uri?> = _outputUri

    private val _outputName = MutableLiveData<String?>()
    val outputName: LiveData<String?> = _outputName

    private val _appliedTrackName = MutableLiveData<String?>()
    val appliedTrackName: LiveData<String?> = _appliedTrackName

    private val _isRunning = MutableLiveData(false)
    val isRunning: LiveData<Boolean> = _isRunning

    private val _logLines = MutableLiveData<MutableList<String>>(mutableListOf())
    val logLines: LiveData<MutableList<String>> = _logLines

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private var job: Job? = null

    fun setOutputFile(uri: Uri) { _outputUri.value = uri; _outputName.value = fileName(uri) }

    fun previewOutputBasename(url: String, onReady: (String) -> Unit) {
        val trimmed = url.trim()
        if (trimmed.isBlank()) {
            onReady(DEFAULT_OUTPUT_BASENAME)
            return
        }
        viewModelScope.launch {
            val suggested = withContext(Dispatchers.IO) {
                runCatching {
                    val json = Python.getInstance().getModule("gpx_bridge").callAttr(
                        "preview_route_names",
                        trimmed,
                        LogCallback { },
                    ).toString()
                    org.json.JSONObject(json).getString("output_basename")
                }.getOrDefault(DEFAULT_OUTPUT_BASENAME)
            }
            onReady(suggested)
        }
    }

    fun run(url: String, mode: String, trackName: String) {
        if (url.isBlank()) { _snackbar.value = "Enter a Google Maps URL"; return }
        val outputUri = _outputUri.value ?: run { _snackbar.value = "Select an output file"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            _appliedTrackName.value = null
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    val ctx = getApplication<Application>()
                    val outTmp = File.createTempFile("gpx_out", ".gpx", ctx.cacheDir)
                    try {
                        val resultJson = Python.getInstance().getModule("gpx_bridge").callAttr(
                            "maps_to_gpx",
                            url.trim(), outTmp.absolutePath, mode, trackName,
                            LogCallback(::log),
                        ).toString()
                        ctx.contentResolver.openOutputStream(outputUri)!!.use { outTmp.inputStream().copyTo(it) }
                        val obj = org.json.JSONObject(resultJson)
                        if (isDefaultTrackName(trackName)) {
                            _appliedTrackName.postValue(obj.getString("track_name"))
                        }
                        log("Done!")
                        _snackbar.postValue("Saved to output file.")
                    } finally {
                        outTmp.delete()
                    }
                }
            } catch (e: CancellationException) {
                log("Cancelled.")
            } catch (e: Exception) {
                log("ERROR: ${e.message}")
                _snackbar.postValue("Error: ${e.message}")
            } finally {
                _isRunning.value = false
            }
        }
    }

    fun cancel() { job?.cancel() }
    fun clearSnackbar() { _snackbar.value = null }

    fun snapshotOutputUri(): Uri? = _outputUri.value

    private fun isDefaultTrackName(name: String): Boolean {
        val trimmed = name.trim()
        return trimmed.isEmpty() || trimmed == DEFAULT_TRACK_NAME
    }

    private fun fileName(uri: Uri): String? =
        getApplication<Application>().contentResolver.query(uri, null, null, null, null)?.use {
            val idx = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (it.moveToFirst() && idx >= 0) it.getString(idx) else null
        }
}
