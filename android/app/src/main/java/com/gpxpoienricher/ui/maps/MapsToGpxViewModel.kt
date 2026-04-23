package com.gpxpoienricher.ui.maps

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import com.gpxpoienricher.core.GpxWriter
import com.gpxpoienricher.core.MapsToGpx
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class MapsToGpxViewModel(app: Application) : AndroidViewModel(app) {

    private val mapsToGpx = MapsToGpx()

    private val _outputUri = MutableLiveData<Uri?>()
    val outputUri: LiveData<Uri?> = _outputUri

    private val _outputName = MutableLiveData<String?>()
    val outputName: LiveData<String?> = _outputName

    private val _isRunning = MutableLiveData(false)
    val isRunning: LiveData<Boolean> = _isRunning

    private val _logLines = MutableLiveData<MutableList<String>>(mutableListOf())
    val logLines: LiveData<MutableList<String>> = _logLines

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private var job: Job? = null

    fun setOutputFile(uri: Uri) {
        _outputUri.value = uri
        _outputName.value = getFileName(uri)
    }

    fun run(url: String, mode: String, trackName: String) {
        if (url.isBlank()) { _snackbar.value = "Enter a Google Maps URL first"; return }
        val outputUri = _outputUri.value ?: run { _snackbar.value = "Select an output file first"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) {
                logs.add(msg)
                _logLines.value = logs.toMutableList()
            }

            try {
                val result = mapsToGpx.convert(url.trim(), mode, onLog = ::log)
                log("Writing GPX...")
                getApplication<Application>().contentResolver
                    .openOutputStream(outputUri)!!.use { stream ->
                        GpxWriter.writeMapsRoute(result.trackPoints, result.waypoints, trackName, stream)
                    }
                log("Done! ${result.trackPoints.size} track points, ${result.waypoints.size} waypoints.")
                _snackbar.value = "Done! Saved to output file."
            } catch (e: CancellationException) {
                log("Cancelled.")
            } catch (e: Exception) {
                log("ERROR: ${e.message}")
                _snackbar.value = "Error: ${e.message}"
            } finally {
                _isRunning.value = false
            }
        }
    }

    fun cancel() {
        job?.cancel()
    }

    fun clearSnackbar() { _snackbar.value = null }

    private fun getFileName(uri: Uri): String? {
        return getApplication<Application>().contentResolver
            .query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cursor.moveToFirst() && idx >= 0) cursor.getString(idx) else null
            }
    }
}
