package com.gpxpoienricher.ui.split

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import com.gpxpoienricher.core.GpxParser
import com.gpxpoienricher.core.GpxWriter
import com.gpxpoienricher.core.Splitter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SplitViewModel(app: Application) : AndroidViewModel(app) {

    private val _inputUri = MutableLiveData<Uri?>()
    val inputUri: LiveData<Uri?> = _inputUri

    private val _inputName = MutableLiveData<String?>()
    val inputName: LiveData<String?> = _inputName

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

    fun setInputFile(uri: Uri) {
        _inputUri.value = uri
        _inputName.value = getFileName(uri)
    }

    fun setOutputFile(uri: Uri) {
        _outputUri.value = uri
        _outputName.value = getFileName(uri)
    }

    fun run(segments: Int) {
        val inputUri = _inputUri.value ?: run { _snackbar.value = "Select an input GPX file first"; return }
        val outputUri = _outputUri.value ?: run { _snackbar.value = "Select an output file first"; return }
        if (segments < 2) { _snackbar.value = "Segments must be at least 2"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) {
                logs.add(msg)
                _logLines.value = logs.toMutableList()
            }

            try {
                log("Reading input GPX...")
                val trackPoints = withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver
                        .openInputStream(inputUri)!!.use { GpxParser.parseTrackPointsFull(it) }
                }
                log("Loaded ${trackPoints.size} track points.")
                log("Splitting into $segments segments (${segments - 1} waypoints)...")
                val waypoints = withContext(Dispatchers.IO) { Splitter.split(trackPoints, segments) }
                log("Writing output GPX...")
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver
                        .openOutputStream(outputUri)!!.use { GpxWriter.writeSplitWaypoints(waypoints, it) }
                }
                log("Done! Wrote ${waypoints.size} split waypoints.")
                _snackbar.value = "Done! Wrote ${waypoints.size} waypoints."
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
