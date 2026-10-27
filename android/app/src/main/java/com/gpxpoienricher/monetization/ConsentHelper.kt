package com.gpxpoienricher.monetization

import android.app.Activity
import com.google.android.ump.ConsentRequestParameters
import com.google.android.ump.ConsentInformation
import com.google.android.ump.UserMessagingPlatform

/**
 * GDPR / EEA consent flow for personalized ads (AdMob + UMP).
 * Always invoke the callback so the app can load non-personalized or no ads as you prefer.
 */
object ConsentHelper {

    fun privacyOptionsRequired(activity: Activity): Boolean =
        UserMessagingPlatform.getConsentInformation(activity).privacyOptionsRequirementStatus ==
            ConsentInformation.PrivacyOptionsRequirementStatus.REQUIRED

    fun showPrivacyOptions(activity: Activity, onFinished: (Boolean) -> Unit) {
        UserMessagingPlatform.showPrivacyOptionsForm(activity) {
            onFinished(UserMessagingPlatform.getConsentInformation(activity).canRequestAds())
        }
    }

    fun requestConsentIfNeeded(activity: Activity, onFinished: (Boolean) -> Unit) {
        val consentInformation = UserMessagingPlatform.getConsentInformation(activity)
        val params = ConsentRequestParameters.Builder().build()
        consentInformation.requestConsentInfoUpdate(
            activity,
            params,
            {
                UserMessagingPlatform.loadAndShowConsentFormIfRequired(activity) { _ ->
                    onFinished(consentInformation.canRequestAds())
                }
            },
            { _ -> onFinished(consentInformation.canRequestAds()) },
        )
    }
}
