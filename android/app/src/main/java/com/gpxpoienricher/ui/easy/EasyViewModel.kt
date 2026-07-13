package com.gpxpoienricher.ui.easy

import android.app.Application
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import com.gpxpoienricher.GpxApp
import com.gpxpoienricher.LogCallback
import com.gpxpoienricher.R
import com.gpxpoienricher.data.ProfileInfo
import com.gpxpoienricher.io.GpxDownloadsExporter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import org.json.JSONArray

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
        /** Waypoint-only ``-milestones.gpx`` files (no track), one per full route when enabled (not detours). */
        val milestonePaths: List<String> = emptyList(),
    )

    private data class InterruptedState(
        val tracksToEnrich: List<String>,
        val trackIndex: Int,
        val profileId: String,
        val outputDir: String,
        val message: String,
        val priorResult: Result?,
    )

    private val _profiles = MutableLiveData<List<ProfileInfo>>(emptyList())
    val profiles: LiveData<List<ProfileInfo>> = _profiles

    private val _isRunning = MutableLiveData(false)
    val isRunning: LiveData<Boolean> = _isRunning

    private val _canResume = MutableLiveData(false)
    val canResume: LiveData<Boolean> = _canResume

    private val _logLines = MutableLiveData<MutableList<String>>(mutableListOf())
    val logLines: LiveData<MutableList<String>> = _logLines

    private val _result = MutableLiveData<Result?>()
    val result: LiveData<Result?> = _result

    private val _snackbar = MutableLiveData<String?>()
    val snackbar: LiveData<String?> = _snackbar

    private var job: Job? = null
    private var interrupted: InterruptedState? = null

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

    /**
     * @param legacyStorageGranted On API 26–28, true when [android.Manifest.permission.WRITE_EXTERNAL_STORAGE]
     * is granted so outputs can be copied into public Downloads.
     */
    fun generate(
        primaryUrl: String,
        extraUrlsMultiline: String,
        profileIndex: Int,
        milestoneParts: Int = 0,
        legacyStorageGranted: Boolean = false,
    ) {
        if (interrupted != null) {
            resume(legacyStorageGranted)
            return
        }

        val url = primaryUrl.trim()
        if (url.isBlank()) { _snackbar.value = "Enter a Google Maps URL"; return }
        val profile = _profiles.value?.getOrNull(profileIndex)
            ?: run { _snackbar.value = "No profile selected"; return }

        job?.cancel()
        job = viewModelScope.launch {
            _isRunning.value = true
            _result.value = null
            _canResume.value = false
            val logs = mutableListOf<String>()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    val ctx = getApplication<Application>()
                    val canExportPublic =
                        Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q || legacyStorageGranted
                    val outputDir = GpxApp.gpxWorkDir()
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

                    handleEasyJson(
                        ctx,
                        resultJson,
                        canExportPublic,
                        ::log,
                        onInterrupted = { state ->
                            interrupted = state
                            _canResume.postValue(true)
                            state.priorResult?.let { _result.postValue(it) }
                            _snackbar.postValue(
                                "Interrupted — tap Resume enrichment to continue. ${state.message}",
                            )
                        },
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

    private fun resume(legacyStorageGranted: Boolean) {
        val state = interrupted ?: return

        job?.cancel()
        job = viewModelScope.launch {
            _isRunning.value = true
            val logs = _logLines.value ?: mutableListOf()
            _logLines.value = logs

            fun log(msg: String) { logs.add(msg); _logLines.postValue(ArrayList(logs)) }

            try {
                withContext(Dispatchers.IO) {
                    val ctx = getApplication<Application>()
                    val canExportPublic =
                        Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q || legacyStorageGranted
                    log("--- Resume ---")

                    val tracksJson = JSONArray(state.tracksToEnrich).toString()
                    val resultJson = Python.getInstance().getModule("gpx_bridge").callAttr(
                        "easy_resume_enrichment",
                        state.profileId,
                        GpxApp.extractProfiles().absolutePath,
                        state.outputDir,
                        tracksJson,
                        state.trackIndex,
                        LogCallback(::log),
                    ).toString()

                    handleEasyJson(
                        ctx,
                        resultJson,
                        canExportPublic,
                        ::log,
                        prior = state.priorResult,
                        onInterrupted = { newState ->
                            interrupted = newState
                            _canResume.postValue(true)
                            mergeAndPostResult(newState.priorResult ?: state.priorResult, newState)
                            _snackbar.postValue(
                                "Interrupted again — tap Resume enrichment. ${newState.message}",
                            )
                        },
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

    private fun handleEasyJson(
        ctx: Application,
        resultJson: String,
        canExportPublic: Boolean,
        log: (String) -> Unit,
        prior: Result? = null,
        onInterrupted: (InterruptedState) -> Unit,
    ) {
        val obj = org.json.JSONObject(resultJson)
        if (obj.optBoolean("cancelled", false)) return

        if (obj.optBoolean("interrupted", false)) {
            val tracksArr = obj.getJSONArray("tracks_to_enrich")
            val tracks = buildList {
                for (i in 0 until tracksArr.length()) add(tracksArr.getString(i))
            }
            onInterrupted(
                InterruptedState(
                    tracksToEnrich = tracks,
                    trackIndex = obj.getInt("track_index"),
                    profileId = obj.getString("profile_id"),
                    outputDir = obj.getString("output_dir"),
                    message = obj.optString("message", "Enrichment interrupted."),
                    priorResult = prior ?: buildPartialResult(obj),
                ),
            )
            return
        }

        interrupted = null
        _canResume.postValue(false)

        val alternatesArr = obj.optJSONArray("alternate_full_paths")
        val alternates = buildList {
            if (alternatesArr != null) {
                for (i in 0 until alternatesArr.length()) add(alternatesArr.getString(i))
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
                for (i in 0 until milestonesArr.length()) add(milestonesArr.getString(i))
            }
        }
        val reusedArr = obj.optJSONArray("reused_paths")
        val reusedPaths = buildSet {
            if (reusedArr != null) {
                for (i in 0 until reusedArr.length()) add(reusedArr.getString(i))
            }
        }

        val res = if (obj.has("start")) {
            Result(
                trackPath = obj.getString("track_path"),
                poiPath = obj.getString("poi_path"),
                start = obj.getString("start"),
                finish = obj.getString("finish"),
                poiCount = obj.getInt("poi_count"),
                trackReused = obj.optBoolean("track_reused", false),
                alternateFullPaths = alternates.ifEmpty { prior?.alternateFullPaths.orEmpty() },
                detourResults = detours.ifEmpty { prior?.detourResults.orEmpty() },
                milestonePaths = milestones.ifEmpty { prior?.milestonePaths.orEmpty() },
            )
        } else {
            mergeResumeResult(prior, obj, detours)
        }

        var resOut = res
        var exportOk = false
        if (canExportPublic) {
            try {
                resOut = remapResultPathsToDownloads(ctx, res, reusedPaths)
                exportOk = true
                log("Copied GPX files to Downloads → ${GpxDownloadsExporter.FOLDER_NAME}.")
            } catch (e: Exception) {
                log("WARN: export to Downloads failed: ${e.message}")
            }
        }
        _result.postValue(resOut)
        val note = if (res.trackReused) "Track reused. " else ""
        val extraPois = res.detourResults.sumOf { it.poiCount }
        val total = res.poiCount + extraPois
        val baseDone =
            if (res.detourResults.isEmpty()) {
                "Done! ${note}$total POI(s) found."
            } else {
                "Done! ${note}$total POI(s) " +
                    "(${res.poiCount} primary + $extraPois detour segment(s))."
            }
        val suffix = when {
            exportOk -> " Saved to Downloads → ${GpxDownloadsExporter.FOLDER_NAME}."
            canExportPublic -> " ${ctx.getString(R.string.snackbar_export_downloads_failed)}"
            else -> ""
        }
        _snackbar.postValue(baseDone + suffix)
    }

    private fun buildPartialResult(obj: org.json.JSONObject): Result? {
        if (!obj.has("track_path")) return null
        val alternatesArr = obj.optJSONArray("alternate_full_paths")
        val alternates = buildList {
            if (alternatesArr != null) {
                for (i in 0 until alternatesArr.length()) add(alternatesArr.getString(i))
            }
        }
        val milestonesArr = obj.optJSONArray("milestone_paths")
        val milestones = buildList {
            if (milestonesArr != null) {
                for (i in 0 until milestonesArr.length()) add(milestonesArr.getString(i))
            }
        }
        return Result(
            trackPath = obj.getString("track_path"),
            poiPath = obj.getString("poi_path"),
            start = obj.optString("start", ""),
            finish = obj.optString("finish", ""),
            poiCount = 0,
            trackReused = obj.optBoolean("track_reused", false),
            alternateFullPaths = alternates,
            milestonePaths = milestones,
        )
    }

    private fun mergeResumeResult(
        prior: Result?,
        obj: org.json.JSONObject,
        detours: List<DetourPoi>,
    ): Result {
        checkNotNull(prior) { "Resume success requires prior result context" }
        return prior.copy(
            poiPath = obj.getString("poi_path"),
            poiCount = obj.getInt("poi_count"),
            detourResults = detours.ifEmpty { prior.detourResults },
        )
    }

    private fun mergeAndPostResult(prior: Result?, state: InterruptedState) {
        val partial = prior ?: state.priorResult ?: return
        _result.postValue(partial)
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

    private fun remapResultPathsToDownloads(
        ctx: Application,
        res: Result,
        reusedPaths: Set<String>,
    ): Result {
        val reusedCanonical = reusedPaths.mapNotNull { runCatching { File(it).canonicalPath }.getOrNull() }.toSet()
        val paths = LinkedHashSet<String>()
        paths.add(res.trackPath)
        paths.add(res.poiPath)
        paths.addAll(res.alternateFullPaths)
        res.detourResults.forEach {
            paths.add(it.trackPath)
            paths.add(it.poiPath)
        }
        paths.addAll(res.milestonePaths)
        val displayByCanonical = LinkedHashMap<String, String>()
        for (p in paths) {
            val f = File(p)
            if (!f.isFile) continue
            val key = f.canonicalPath
            if (key !in displayByCanonical) {
                val mode = if (key in reusedCanonical) {
                    GpxDownloadsExporter.ExportMode.SKIP_IF_EXISTS
                } else {
                    GpxDownloadsExporter.ExportMode.OVERWRITE
                }
                displayByCanonical[key] = GpxDownloadsExporter.exportFile(ctx, f, mode = mode)
            }
        }
        fun mapPath(p: String): String {
            val f = File(p)
            return if (f.isFile) displayByCanonical[f.canonicalPath] ?: p else p
        }
        return res.copy(
            trackPath = mapPath(res.trackPath),
            poiPath = mapPath(res.poiPath),
            alternateFullPaths = res.alternateFullPaths.map(::mapPath),
            detourResults = res.detourResults.map { d ->
                d.copy(trackPath = mapPath(d.trackPath), poiPath = mapPath(d.poiPath))
            },
            milestonePaths = res.milestonePaths.map(::mapPath),
        )
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
