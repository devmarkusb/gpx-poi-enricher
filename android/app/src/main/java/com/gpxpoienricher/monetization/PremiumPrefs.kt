package com.gpxpoienricher.monetization

import android.content.Context

/** Local cache of “remove ads” entitlement; kept in sync with Play Billing. */
object PremiumPrefs {

    private const val PREFS_NAME = "gpx_monetization"
    private const val KEY_AD_FREE = "ad_free"

    private fun sp(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun isAdFree(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_AD_FREE, false)

    fun setAdFree(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean(KEY_AD_FREE, value).apply()
    }
}
