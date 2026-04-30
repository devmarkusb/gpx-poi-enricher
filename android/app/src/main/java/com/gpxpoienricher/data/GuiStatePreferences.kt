package com.gpxpoienricher.data

import android.content.Context
import com.gpxpoienricher.R

/**
 * Persists form fields and the selected bottom tab across app launches.
 * Uses app-private [SharedPreferences] (same idea as desktop QSettings).
 */
object GuiStatePreferences {

    private const val PREFS_NAME = "gpx_gui_state"

    private const val K_NAV = "nav_destination"

    private const val K_EASY_PRIMARY = "easy_primary_url"
    private const val K_EASY_EXTRA = "easy_extra_urls"
    private const val K_EASY_PROFILE = "easy_profile_id"
    private const val K_EASY_MILESTONE_PARTS = "easy_milestone_parts"

    private const val K_ENR_IN = "enricher_input_uri"
    private const val K_ENR_OUT = "enricher_output_uri"
    private const val K_ENR_PROFILE = "enricher_profile_id"
    private const val K_ENR_MAX = "enricher_max_km"
    private const val K_ENR_SAMPLE = "enricher_sample_km"

    private const val K_SPL_IN = "split_input_uri"
    private const val K_SPL_OUT = "split_output_uri"
    private const val K_SPL_SEG = "split_segments"

    private const val K_MAPS_URL = "maps_url"
    private const val K_MAPS_MODE = "maps_mode"
    private const val K_MAPS_TRACK = "maps_track_name"
    private const val K_MAPS_OUT = "maps_output_uri"

    private fun sp(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun isKnownNavDestination(id: Int): Boolean = when (id) {
        R.id.nav_easy, R.id.nav_enricher, R.id.nav_split, R.id.nav_maps -> true
        else -> false
    }

    fun readNavDestinationId(ctx: Context): Int {
        val id = sp(ctx).getInt(K_NAV, R.id.nav_easy)
        return if (isKnownNavDestination(id)) id else R.id.nav_easy
    }

    fun writeNavDestinationId(ctx: Context, destinationId: Int) {
        if (isKnownNavDestination(destinationId)) {
            sp(ctx).edit().putInt(K_NAV, destinationId).apply()
        }
    }

    // --- Easy ----------------------------------------------------------------

    fun readEasyPrimaryUrl(ctx: Context): String = sp(ctx).getString(K_EASY_PRIMARY, "") ?: ""

    fun readEasyExtraUrls(ctx: Context): String = sp(ctx).getString(K_EASY_EXTRA, "") ?: ""

    fun readEasyProfileId(ctx: Context): String? = sp(ctx).getString(K_EASY_PROFILE, null)

    /** 0 = off; N ≥ 2 writes waypoint-only ``-milestones.gpx`` beside each track (see Easy mode). */
    fun readEasyMilestoneParts(ctx: Context): Int =
        sp(ctx).getInt(K_EASY_MILESTONE_PARTS, 0).coerceIn(0, 9999)

    fun writeEasy(
        ctx: Context,
        primaryUrl: String,
        extraUrls: String,
        profileId: String?,
        milestoneParts: Int = 0,
    ) {
        val e = sp(ctx).edit()
        e.putString(K_EASY_PRIMARY, primaryUrl)
        e.putString(K_EASY_EXTRA, extraUrls)
        if (profileId.isNullOrBlank()) e.remove(K_EASY_PROFILE) else e.putString(K_EASY_PROFILE, profileId)
        e.putInt(K_EASY_MILESTONE_PARTS, milestoneParts.coerceIn(0, 9999))
        e.apply()
    }

    // --- Enricher ------------------------------------------------------------

    fun readEnricherInputUri(ctx: Context): String? = sp(ctx).getString(K_ENR_IN, null)

    fun readEnricherOutputUri(ctx: Context): String? = sp(ctx).getString(K_ENR_OUT, null)

    fun readEnricherProfileId(ctx: Context): String? = sp(ctx).getString(K_ENR_PROFILE, null)

    fun readEnricherMaxKm(ctx: Context): String = sp(ctx).getString(K_ENR_MAX, "") ?: ""

    fun readEnricherSampleKm(ctx: Context): String = sp(ctx).getString(K_ENR_SAMPLE, "") ?: ""

    fun writeEnricher(
        ctx: Context,
        inputUri: String?,
        outputUri: String?,
        profileId: String?,
        maxKm: String,
        sampleKm: String,
    ) {
        val e = sp(ctx).edit()
        if (inputUri.isNullOrBlank()) e.remove(K_ENR_IN) else e.putString(K_ENR_IN, inputUri)
        if (outputUri.isNullOrBlank()) e.remove(K_ENR_OUT) else e.putString(K_ENR_OUT, outputUri)
        if (profileId.isNullOrBlank()) e.remove(K_ENR_PROFILE) else e.putString(K_ENR_PROFILE, profileId)
        e.putString(K_ENR_MAX, maxKm)
        e.putString(K_ENR_SAMPLE, sampleKm)
        e.apply()
    }

    // --- Split ---------------------------------------------------------------

    fun readSplitInputUri(ctx: Context): String? = sp(ctx).getString(K_SPL_IN, null)

    fun readSplitOutputUri(ctx: Context): String? = sp(ctx).getString(K_SPL_OUT, null)

    fun readSplitSegments(ctx: Context): String = sp(ctx).getString(K_SPL_SEG, "10") ?: "10"

    fun writeSplit(ctx: Context, inputUri: String?, outputUri: String?, segments: String) {
        val e = sp(ctx).edit()
        if (inputUri.isNullOrBlank()) e.remove(K_SPL_IN) else e.putString(K_SPL_IN, inputUri)
        if (outputUri.isNullOrBlank()) e.remove(K_SPL_OUT) else e.putString(K_SPL_OUT, outputUri)
        e.putString(K_SPL_SEG, segments)
        e.apply()
    }

    // --- Maps → GPX ----------------------------------------------------------

    fun readMapsUrl(ctx: Context): String = sp(ctx).getString(K_MAPS_URL, "") ?: ""

    /** One of: driving, cycling, walking */
    fun readMapsMode(ctx: Context): String = sp(ctx).getString(K_MAPS_MODE, "driving") ?: "driving"

    fun readMapsTrackName(ctx: Context): String = sp(ctx).getString(K_MAPS_TRACK, "Route") ?: "Route"

    fun readMapsOutputUri(ctx: Context): String? = sp(ctx).getString(K_MAPS_OUT, null)

    fun writeMaps(ctx: Context, url: String, mode: String, trackName: String, outputUri: String?) {
        val e = sp(ctx).edit()
        e.putString(K_MAPS_URL, url)
        e.putString(K_MAPS_MODE, mode)
        e.putString(K_MAPS_TRACK, trackName)
        if (outputUri.isNullOrBlank()) e.remove(K_MAPS_OUT) else e.putString(K_MAPS_OUT, outputUri)
        e.apply()
    }
}
