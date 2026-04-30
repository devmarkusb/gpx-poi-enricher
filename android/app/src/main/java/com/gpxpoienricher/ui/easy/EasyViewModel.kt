package com.gpxpoienricher.ui.easy

import android.app.Application
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

class EasyViewModel(app: Application) : AndroidViewModel(app) {

    data class DetourPoi(val trackPath: String, val poiPath: String, val poiCount: Int)

    data class Result(
        val trackPath: String,
        val poiPath: String,
        val start: String,
        val finish: String,
        val poiCount: Int,
        val trackReused: Boolean,
        val alternateFullPaths: List<String> = emptyList(),
        val detourResults: List<DetourPoi> = emptyList(),
        /** Waypoint-only ``-milestones.gpx`` files (no track), one per enriched route when enabled. */
        val milestonePaths: List<String> = emptyList(),
    )

    private val _profiles = MutableLiveData<List<ProfileInfo>>(emptyList())
    val profiles: LiveData<List<ProfileInfo>> = _profiles

    private val _isRunning = MutableLiveData(false)
    val isRunning: LiveData<Boolean> = _isRunning

    private val _logLines = MutableLiveData<MutableList<String>>(mutableListOf())
    val logLines: LiveData<MutableList<String>> = _logLines

    private val _result = MutableLiveData<Result?>()
    val result: LiveData<Result?> = _result

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private var job: Job? = null

    init {
        viewModelScope.launch(Dispatchers.IO) {
            val dir = GpxApp.extractProfiles()
            val json = Python.getInstance().getModule("gpx_bridge")
                .callAttr("list_profiles", dir.absolutePath).toString()
            _profiles.postValue(parseProfiles(json))
        }
    }

    fun generate(primaryUrl: String, extraUrlsMultiline: String, profileIndex: Int, milestoneParts: Int = 0) {
        val url = primaryUrl.trim()
        if (url.isBlank()) { _snackbar.value = "Enter a Google Maps URL"; return }
        val profile = _profiles.value?.getOrNull(profileIndex)
            ?: run { _snackbar.value = "No profile selected"; return }

        job = viewModelScope.launch {
            _isRunning.value = true
            _result.value = null
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    val ctx = getApplication<Application>()
                    val outputDir = ctx.getExternalFilesDir("gpx") ?: ctx.filesDir.resolve("gpx")
                    outputDir.mkdirs()

                    val parts = milestoneParts.coerceIn(0, 9999)
                    val resultJson = Python.getInstance().getModule("gpx_bridge").callAttr(
                        "easy_generate",
                        url,
                        extraUrlsMultiline,
                        profile.id,
                        GpxApp.extractProfiles().absolutePath,
                        outputDir.absolutePath,
                        LogCallback(::log),
                        parts,
                    ).toString()

                    val obj = org.json.JSONObject(resultJson)
                    if (obj.optBoolean("cancelled", false)) return@withContext

                    val alternatesArr = obj.optJSONArray("alternate_full_paths")
                    val alternates = buildList {
                        if (alternatesArr != null) {
                            for (i in 0 until alternatesArr.length()) {
                                add(alternatesArr.getString(i))
                            }
                        }
                    }
                    val detoursArr = obj.optJSONArray("detour_results")
                    val detours = buildList {
                        if (detoursArr != null) {
                            for (i in 0 until detoursArr.length()) {
                                val d = detoursArr.getJSONObject(i)
                                add(
                                    DetourPoi(
                                        trackPath = d.getString("track_path"),
                                        poiPath = d.getString("poi_path"),
                                        poiCount = d.getInt("poi_count"),
                                    ),
                                )
                            }
                        }
                    }
                    val milestonesArr = obj.optJSONArray("milestone_paths")
                    val milestones = buildList {
                        if (milestonesArr != null) {
                            for (i in 0 until milestonesArr.length()) {
                                add(milestonesArr.getString(i))
                            }
                        }
                    }
                    val res = Result(
                        trackPath = obj.getString("track_path"),
                        poiPath = obj.getString("poi_path"),
                        start = obj.getString("start"),
                        finish = obj.getString("finish"),
                        poiCount = obj.getInt("poi_count"),
                        trackReused = obj.getBoolean("track_reused"),
                        alternateFullPaths = alternates,
                        detourResults = detours,
                        milestonePaths = milestones,
                    )
                    _result.postValue(res)
                    val note = if (res.trackReused) "Track reused. " else ""
                    val extraPois = res.detourResults.sumOf { it.poiCount }
                    val total = res.poiCount + extraPois
                    val doneMsg =
                        if (res.detourResults.isEmpty()) {
                            "Done! ${note}$total POI(s) found."
                        } else {
                            "Done! ${note}$total POI(s) " +
                                "(${res.poiCount} primary + $extraPois detour segment(s))."
                        }
                    _snackbar.postValue(doneMsg)
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

    fun cancel() {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { Python.getInstance().getModule("gpx_bridge").callAttr("cancel") }
        }
        job?.cancel()
    }

    fun clearSnackbar() { _snackbar.value = null }

    /** For persisting the selected profile across sessions. */
    fun profileIdAtSpinnerIndex(index: Int): String? = _profiles.value?.getOrNull(index)?.id

    private fun parseProfiles(json: String): List<ProfileInfo> {
        val arr = org.json.JSONArray(json)
        return (0 until arr.length())
            .map { arr.getJSONObject(it).let { o -> ProfileInfo(o.getString("id"), o.getString("description")) } }
            .sortedBy { it.description }
    }
}
