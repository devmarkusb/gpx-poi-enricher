package com.gpxpoienricher.ui.enricher

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import com.gpxpoienricher.core.Enricher
import com.gpxpoienricher.core.GpxParser
import com.gpxpoienricher.core.GpxWriter
import com.gpxpoienricher.core.ProfileLoader
import com.gpxpoienricher.data.Profile
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class EnricherViewModel(app: Application) : AndroidViewModel(app) {

    private val enricher = Enricher()

    private val _profiles = MutableLiveData<List<Profile>>(emptyList())
    val profiles: LiveData<List<Profile>> = _profiles

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

    init {
        _profiles.value = ProfileLoader.loadAll(app)
    }

    fun setInputFile(uri: Uri) {
        _inputUri.value = uri
        _inputName.value = getFileName(uri)
    }

    fun setOutputFile(uri: Uri) {
        _outputUri.value = uri
        _outputName.value = getFileName(uri)
    }

    fun run(profileIndex: Int, maxKmOverride: Double?, sampleKmOverride: Double?) {
        val profiles = _profiles.value ?: return
        val profile = profiles.getOrNull(profileIndex) ?: return
        val inputUri = _inputUri.value ?: run { _snackbar.value = "Select an input GPX file first"; return }
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
                log("Reading input GPX...")
                val trackPoints = getApplication<Application>().contentResolver
                    .openInputStream(inputUri)!!.use { GpxParser.parseTrackPoints(it) }

                val pois = enricher.enrich(
                    trackPoints = trackPoints,
                    profile = profile,
                    maxKm = maxKmOverride,
                    sampleKm = sampleKmOverride,
                    onLog = ::log
                )

                log("Writing ${pois.size} waypoints to output...")
                getApplication<Application>().contentResolver
                    .openOutputStream(outputUri)!!.use { stream ->
                        GpxWriter.writeWaypoints(pois, profile.symbol, profile.description, stream)
                    }
                log("Done! Wrote ${pois.size} waypoints.")
                _snackbar.value = "Done! Found ${pois.size} POIs."
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
