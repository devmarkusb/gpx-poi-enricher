package com.gpxpoienricher.ui.split

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

    fun setInputFile(uri: Uri) { _inputUri.value = uri; _inputName.value = fileName(uri) }
    fun setOutputFile(uri: Uri) { _outputUri.value = uri; _outputName.value = fileName(uri) }

    fun run(segments: Int) {
        if (segments < 2) { _snackbar.value = "Segments must be at least 2"; return }
        val inputUri = _inputUri.value ?: run { _snackbar.value = "Select an input GPX file"; return }
        val outputUri = _outputUri.value ?: run { _snackbar.value = "Select an output file"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    val ctx = getApplication<Application>()
                    val inTmp = File.createTempFile("gpx_in", ".gpx", ctx.cacheDir)
                    val outTmp = File.createTempFile("gpx_out", ".gpx", ctx.cacheDir)
                    try {
                        ctx.contentResolver.openInputStream(inputUri)!!.use { it.copyTo(inTmp.outputStream()) }

                        Python.getInstance().getModule("gpx_bridge").callAttr(
                            "split",
                            inTmp.absolutePath, outTmp.absolutePath,
                            segments, LogCallback(::log)
                        )

                        ctx.contentResolver.openOutputStream(outputUri)!!.use { outTmp.inputStream().copyTo(it) }
                        log("Done! Wrote ${segments - 1} split waypoints.")
                        _snackbar.postValue("Done!")
                    } finally {
                        inTmp.delete(); outTmp.delete()
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

    private fun fileName(uri: Uri): String? =
        getApplication<Application>().contentResolver.query(uri, null, null, null, null)?.use {
            val idx = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (it.moveToFirst() && idx >= 0) it.getString(idx) else null
        }
}
