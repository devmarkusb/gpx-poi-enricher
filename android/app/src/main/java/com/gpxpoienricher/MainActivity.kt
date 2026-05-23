package com.gpxpoienricher

import android.os.Bundle
import android.util.Log
import android.view.Menu
import android.view.MenuItem
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isGone
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.NavigationUI
import androidx.navigation.ui.setupWithNavController
import com.google.android.gms.ads.AdError
import com.google.android.gms.ads.AdRequest
import com.google.android.gms.ads.AdSize
import com.google.android.gms.ads.AdView
import com.google.android.gms.ads.FullScreenContentCallback
import com.google.android.gms.ads.LoadAdError
import com.google.android.gms.ads.interstitial.InterstitialAd
import com.google.android.gms.ads.interstitial.InterstitialAdLoadCallback
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.ActivityMainBinding
import com.gpxpoienricher.monetization.ConsentHelper
import com.gpxpoienricher.monetization.PlayStoreMonetization
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var bannerAdView: AdView? = null
    private var interstitialAd: InterstitialAd? = null
    private var interstitialAdLoading = false
    private var adsConsentReady = false
    private var restoringInitialDestination = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.title = getString(R.string.app_name)

        val monetization = (application as GpxApp).monetization
        observeMonetization(monetization)

        ConsentHelper.requestConsentIfNeeded(this) {
            adsConsentReady = true
            if (!monetization.adFree.value) {
                ensureBannerAd(monetization)
                ensureInterstitialAd(monetization)
            }
        }

        val navHostFragment = supportFragmentManager
            .findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        val navController = navHostFragment.navController
        binding.bottomNav.setupWithNavController(navController)
        binding.bottomNav.setOnItemSelectedListener { item ->
            val currentDestinationId = navController.currentDestination?.id
            if (item.itemId == currentDestinationId) {
                return@setOnItemSelectedListener true
            }

            if (restoringInitialDestination) {
                restoringInitialDestination = false
                return@setOnItemSelectedListener NavigationUI.onNavDestinationSelected(
                    item,
                    navController,
                )
            }

            if (shouldShowEasySwitchInterstitial(currentDestinationId, item.itemId) &&
                showEasySwitchInterstitial(monetization) {
                    NavigationUI.onNavDestinationSelected(item, navController)
                }
            ) {
                return@setOnItemSelectedListener false
            }

            NavigationUI.onNavDestinationSelected(item, navController)
        }

        val savedDest = GuiStatePreferences.readNavDestinationId(this)
        binding.bottomNav.post {
            if (savedDest != navController.currentDestination?.id) {
                restoringInitialDestination = true
                binding.bottomNav.selectedItemId = savedDest
            }
        }
        navController.addOnDestinationChangedListener { _, destination, _ ->
            GuiStatePreferences.writeNavDestinationId(this@MainActivity, destination.id)
        }
    }

    private fun observeMonetization(monetization: PlayStoreMonetization) {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    monetization.adFree.collect { adFree ->
                        if (adFree) {
                            tearDownBannerAd()
                            tearDownInterstitialAd()
                            binding.adBannerContainer.isGone = true
                        } else {
                            binding.adBannerContainer.isGone = false
                            if (adsConsentReady) {
                                ensureBannerAd(monetization)
                                ensureInterstitialAd(monetization)
                            }
                        }
                        invalidateOptionsMenu()
                    }
                }
                launch {
                    monetization.toastMessages.collect { msg ->
                        Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
                    }
                }
            }
        }
    }

    private fun ensureBannerAd(monetization: PlayStoreMonetization) {
        if (bannerAdView != null) return
        if (monetization.adFree.value) return
        if (!adsConsentReady) return

        val adView = AdView(this)
        adView.adUnitId = getString(R.string.admob_banner_ad_unit_id)
        val adWidthDp = (resources.displayMetrics.widthPixels / resources.displayMetrics.density).toInt()
        adView.setAdSize(AdSize.getCurrentOrientationAnchoredAdaptiveBannerAdSize(this, adWidthDp))
        adView.layoutParams = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
        )
        binding.adBannerContainer.removeAllViews()
        binding.adBannerContainer.addView(adView)
        adView.loadAd(AdRequest.Builder().build())
        bannerAdView = adView
    }

    private fun tearDownBannerAd() {
        bannerAdView?.destroy()
        binding.adBannerContainer.removeAllViews()
        bannerAdView = null
    }

    private fun ensureInterstitialAd(monetization: PlayStoreMonetization) {
        if (interstitialAd != null) return
        if (interstitialAdLoading) return
        if (monetization.adFree.value) return
        if (!adsConsentReady) return

        val adUnitId = getString(R.string.admob_interstitial_ad_unit_id).trim()
        if (adUnitId.isEmpty()) return

        interstitialAdLoading = true
        InterstitialAd.load(
            this,
            adUnitId,
            AdRequest.Builder().build(),
            object : InterstitialAdLoadCallback() {
                override fun onAdLoaded(ad: InterstitialAd) {
                    interstitialAdLoading = false
                    if (
                        isFinishing ||
                        isDestroyed ||
                        monetization.adFree.value ||
                        !adsConsentReady
                    ) {
                        return
                    }
                    interstitialAd = ad
                }

                override fun onAdFailedToLoad(error: LoadAdError) {
                    interstitialAdLoading = false
                    interstitialAd = null
                    Log.w(TAG, "Interstitial load failed: ${error.code} ${error.message}")
                }
            },
        )
    }

    private fun showEasySwitchInterstitial(
        monetization: PlayStoreMonetization,
        continueNavigation: () -> Unit,
    ): Boolean {
        if (monetization.adFree.value || !adsConsentReady) return false
        val ad = interstitialAd ?: run {
            ensureInterstitialAd(monetization)
            return false
        }

        interstitialAd = null
        ad.fullScreenContentCallback = object : FullScreenContentCallback() {
            override fun onAdDismissedFullScreenContent() {
                ensureInterstitialAd(monetization)
                continueIfActivityAlive(continueNavigation)
            }

            override fun onAdFailedToShowFullScreenContent(error: AdError) {
                Log.w(TAG, "Interstitial show failed: ${error.code} ${error.message}")
                ensureInterstitialAd(monetization)
                continueIfActivityAlive(continueNavigation)
            }
        }
        ad.show(this)
        return true
    }

    private fun shouldShowEasySwitchInterstitial(
        fromDestinationId: Int?,
        toDestinationId: Int,
    ): Boolean {
        if (fromDestinationId == null) return false
        if (fromDestinationId == toDestinationId) return false
        return fromDestinationId == R.id.nav_easy || toDestinationId == R.id.nav_easy
    }

    private fun continueIfActivityAlive(action: () -> Unit) {
        if (!isFinishing && !isDestroyed) {
            action()
        }
    }

    private fun tearDownInterstitialAd() {
        interstitialAd?.fullScreenContentCallback = null
        interstitialAd = null
        interstitialAdLoading = false
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_activity_menu, menu)
        return true
    }

    override fun onPrepareOptionsMenu(menu: Menu): Boolean {
        val adFree = (application as GpxApp).monetization.adFree.value
        menu.findItem(R.id.action_remove_ads)?.isVisible = !adFree
        return super.onPrepareOptionsMenu(menu)
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        val monetization = (application as GpxApp).monetization
        when (item.itemId) {
            R.id.action_remove_ads -> {
                monetization.launchRemoveAdsFlow(this)
                return true
            }
            R.id.action_restore_purchases -> {
                monetization.restorePurchases()
                Snackbar.make(binding.root, R.string.msg_restore_purchases_done, Snackbar.LENGTH_SHORT).show()
                return true
            }
        }
        return super.onOptionsItemSelected(item)
    }

    override fun onPause() {
        bannerAdView?.pause()
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        bannerAdView?.resume()
    }

    override fun onDestroy() {
        tearDownBannerAd()
        tearDownInterstitialAd()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "MainActivity"
    }
}
