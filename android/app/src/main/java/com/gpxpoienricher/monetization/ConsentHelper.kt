package com.gpxpoienricher.monetization

import android.app.Activity
import com.google.android.ump.ConsentRequestParameters
import com.google.android.ump.UserMessagingPlatform

/**
 * GDPR / EEA consent flow for personalized ads (AdMob + UMP).
 * Always invoke the callback so the app can load non-personalized or no ads as you prefer.
 */
object ConsentHelper {

    fun requestConsentIfNeeded(activity: Activity, onFinished: () -> Unit) {
        val consentInformation = UserMessagingPlatform.getConsentInformation(activity)
        val params = ConsentRequestParameters.Builder().build()
        consentInformation.requestConsentInfoUpdate(
            activity,
            params,
            {
                UserMessagingPlatform.loadAndShowConsentFormIfRequired(activity) { _ ->
                    onFinished()
                }
            },
            { _ -> onFinished() },
        )
    }
}
