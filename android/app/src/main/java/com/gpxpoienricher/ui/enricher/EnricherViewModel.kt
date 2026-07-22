package com.gpxpoienricher.ui.enricher

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import com.gpxpoienricher.GpxApp
import com.gpxpoienricher.LogCallback
import com.gpxpoienricher.data.ProfileInfo
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

class EnricherViewModel(app: Application) : AndroidViewModel(app) {

    private data class ResumeState(
        val inputWorkPath: String,
        val outputWorkPath: String,
        val profileId: String,
        val outputUri: Uri,
        val maxKm: Double?,
        val sampleKm: Double?,
        val message: String,
    )

    private val _profiles = MutableLiveData<List<ProfileInfo>>(emptyList())
    val profiles: LiveData<List<ProfileInfo>> = _profiles

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

    private val _canResume = MutableLiveData(false)
    val canResume: LiveData<Boolean> = _canResume

    private val _logLines = MutableLiveData<MutableList<String>>(mutableListOf())
    val logLines: LiveData<MutableList<String>> = _logLines

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private var job: Job? = null
    private var resumeState: ResumeState? = null

    init {
        reloadProfiles()
    }

    fun reloadProfiles() {
        viewModelScope.launch(Dispatchers.IO) {
            val dir = GpxApp.extractProfiles()
            val json = Python.getInstance().getModule("gpx_bridge")
                .callAttr("list_profiles", dir.absolutePath).toString()
            _profiles.postValue(parseProfiles(json))
        }
    }

    fun setInputFile(uri: Uri) {
        _inputUri.value = uri
        _inputName.value = fileName(uri)
        resumeState = null
        _canResume.value = false
    }

    fun setOutputFile(uri: Uri) {
        _outputUri.value = uri
        _outputName.value = fileName(uri)
        resumeState = null
        _canResume.value = false
    }

    fun run(profileIndex: Int, maxKm: Double?, sampleKm: Double?) {
        if (resumeState != null) {
            resume()
            return
        }

        val profile = _profiles.value?.getOrNull(profileIndex)
            ?: run { _snackbar.value = "No profile selected"; return }
        val inputUri = _inputUri.value ?: run { _snackbar.value = "Select an input GPX file"; return }
        val outputUri = _outputUri.value ?: run { _snackbar.value = "Select an output file"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            _canResume.value = false
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    runEnrichment(
                        profile.id,
                        inputUri,
                        outputUri,
                        maxKm,
                        sampleKm,
                        resume = false,
                        log = ::log,
                    )
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

    private fun resume() {
        val state = resumeState ?: return

        job = viewModelScope.launch {
            _isRunning.value = true
            val logs = _logLines.value ?: mutableListOf()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    log("--- Resume ---")
                    runEnrichment(
                        state.profileId,
                        Uri.fromFile(File(state.inputWorkPath)),
                        state.outputUri,
                        state.maxKm,
                        state.sampleKm,
                        resume = true,
                        log = ::log,
                        inputWorkPath = state.inputWorkPath,
                        outputWorkPath = state.outputWorkPath,
                    )
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

    private fun runEnrichment(
        profileId: String,
        inputUri: Uri,
        outputUri: Uri,
        maxKm: Double?,
        sampleKm: Double?,
        resume: Boolean,
        log: (String) -> Unit,
        inputWorkPath: String? = null,
        outputWorkPath: String? = null,
    ) {
        val ctx = getApplication<Application>()
        val workDir = GpxApp.gpxWorkDir().apply { mkdirs() }
        val tag = workTag(inputUri, profileId)
        val inWork =
            if (inputWorkPath != null) File(inputWorkPath) else File(workDir, "enrich-in-$tag.gpx")
        val outWork =
            if (outputWorkPath != null) File(outputWorkPath) else File(workDir, "enrich-out-$tag.gpx")

        if (!resume) {
            ctx.contentResolver.openInputStream(inputUri)!!.use { it.copyTo(inWork.outputStream()) }
        }

        val resultJson = Python.getInstance().getModule("gpx_bridge").callAttr(
            "enrich",
            inWork.absolutePath,
            outWork.absolutePath,
            profileId,
            GpxApp.extractProfiles().absolutePath,
            maxKm,
            sampleKm,
            LogCallback(log),
            resume,
        ).toString()

        val obj = org.json.JSONObject(resultJson)
        if (obj.optBoolean("interrupted", false)) {
            resumeState = ResumeState(
                inputWorkPath = inWork.absolutePath,
                outputWorkPath = outWork.absolutePath,
                profileId = profileId,
                outputUri = outputUri,
                maxKm = maxKm,
                sampleKm = sampleKm,
                message = obj.optString("message", "Enrichment interrupted."),
            )
            _canResume.postValue(true)
            _snackbar.postValue(
                "Interrupted — tap Resume enrichment to continue. ${resumeState?.message}",
            )
            return
        }

        val count = obj.getInt("poi_count")
        ctx.contentResolver.openOutputStream(outputUri)!!.use { outWork.inputStream().copyTo(it) }
        inWork.delete()
        outWork.delete()
        resumeState = null
        _canResume.postValue(false)
        log("Done! Wrote $count waypoints.")
        _snackbar.postValue("Done! Found $count POIs.")
    }

    private fun workTag(inputUri: Uri, profileId: String): String {
        val name = fileName(inputUri) ?: inputUri.toString()
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$name|$profileId".toByteArray())
            .take(8)
            .joinToString("") { "%02x".format(it) }
        return "$profileId-$digest"
    }

    fun cancel() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { Python.getInstance().getModule("gpx_bridge").callAttr("cancel") }
        }
        job?.cancel()
    }

    fun clearSnackbar() { _snackbar.value = null }

    fun profileIdAtSpinnerIndex(index: Int): String? = _profiles.value?.getOrNull(index)?.id

    fun snapshotInputUri(): Uri? = _inputUri.value

    fun snapshotOutputUri(): Uri? = _outputUri.value

    private fun fileName(uri: Uri): String? =
        getApplication<Application>().contentResolver.query(uri, null, null, null, null)?.use {
            val idx = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (it.moveToFirst() && idx >= 0) it.getString(idx) else null
        }

    private fun parseProfiles(json: String): List<ProfileInfo> {
        val arr = org.json.JSONArray(json)
        return (0 until arr.length())
            .map { i ->
                val o = arr.getJSONObject(i)
                ProfileInfo(
                    o.getString("id"),
                    o.getString("description"),
                    o.optString("source", "builtin"),
                )
            }
            .sortedWith(compareBy({ it.source == "user" }, { it.description.lowercase() }))
    }
}
