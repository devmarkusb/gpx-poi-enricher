package com.gpxpoienricher.monetization

import android.app.Activity
import android.os.SystemClock
import android.util.Log
import com.google.android.gms.ads.AdError
import com.google.android.gms.ads.AdRequest
import com.google.android.gms.ads.FullScreenContentCallback
import com.google.android.gms.ads.LoadAdError
import com.google.android.gms.ads.interstitial.InterstitialAd
import com.google.android.gms.ads.interstitial.InterstitialAdLoadCallback

/**
 * Interstitials shown only at natural break points (a finished enrichment run), never on
 * navigation or while work is in progress, and rate-limited so ads stay a minority of the
 * session — the constraints behind AdMob's "more ads than content" policy.
 */
class InterstitialAds(
    private val adUnitId: String,
    private val isAdFree: () -> Boolean,
) {

    private var ad: InterstitialAd? = null
    private var loading = false
    private var shownThisSession = 0
    private var lastShownElapsedMs = 0L

    var consentReady: Boolean = false
        private set

    fun onConsentReady(activity: Activity) {
        consentReady = true
        preload(activity)
    }

    fun preload(activity: Activity) {
        if (!canRequest()) return
        if (ad != null || loading) return

        loading = true
        InterstitialAd.load(
            activity,
            adUnitId,
            AdRequest.Builder().build(),
            object : InterstitialAdLoadCallback() {
                override fun onAdLoaded(loaded: InterstitialAd) {
                    loading = false
                    ad = if (canRequest()) loaded else null
                }

                override fun onAdFailedToLoad(error: LoadAdError) {
                    loading = false
                    ad = null
                    Log.w(TAG, "Interstitial load failed: ${error.code} ${error.message}")
                }
            },
        )
    }

    /** Shows a cached interstitial if the caps allow it; never blocks the caller's flow. */
    fun showAfterCompletedTask(activity: Activity) {
        if (!canRequest() || !withinFrequencyCaps()) {
            preload(activity)
            return
        }
        val ready = ad ?: run {
            preload(activity)
            return
        }

        ad = null
        ready.fullScreenContentCallback = object : FullScreenContentCallback() {
            override fun onAdDismissedFullScreenContent() = preload(activity)

            override fun onAdFailedToShowFullScreenContent(error: AdError) {
                Log.w(TAG, "Interstitial show failed: ${error.code} ${error.message}")
                preload(activity)
            }
        }
        shownThisSession++
        lastShownElapsedMs = SystemClock.elapsedRealtime()
        ready.show(activity)
    }

    fun release() {
        ad?.fullScreenContentCallback = null
        ad = null
        loading = false
    }

    private fun canRequest(): Boolean =
        consentReady && !isAdFree() && adUnitId.isNotEmpty()

    private fun withinFrequencyCaps(): Boolean {
        if (shownThisSession >= MAX_PER_SESSION) return false
        if (lastShownElapsedMs == 0L) return true
        return SystemClock.elapsedRealtime() - lastShownElapsedMs >= MIN_INTERVAL_MS
    }

    companion object {
        private const val TAG = "InterstitialAds"
        private const val MAX_PER_SESSION = 2
        private const val MIN_INTERVAL_MS = 3 * 60 * 1000L
    }
}
