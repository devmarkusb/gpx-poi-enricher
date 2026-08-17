package com.gpxpoienricher

import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.isGone
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.setupWithNavController
import com.google.android.gms.ads.AdRequest
import com.google.android.gms.ads.AdSize
import com.google.android.gms.ads.AdView
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.ActivityMainBinding
import com.gpxpoienricher.monetization.ConsentHelper
import com.gpxpoienricher.monetization.InterstitialAds
import com.gpxpoienricher.monetization.PlayStoreMonetization
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var interstitialAds: InterstitialAds
    private var bannerAdView: AdView? = null
    private var adsConsentReady = false
    private var imeVisible = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.title = getString(R.string.app_name)

        val monetization = (application as GpxApp).monetization
        interstitialAds = InterstitialAds(
            adUnitId = getString(R.string.admob_interstitial_ad_unit_id).trim(),
            isAdFree = { monetization.adFree.value },
        )
        observeMonetization(monetization)
        observeImeForBanner(monetization)

        ConsentHelper.requestConsentIfNeeded(this) {
            adsConsentReady = true
            if (!monetization.adFree.value) {
                ensureBannerAd(monetization)
                interstitialAds.onConsentReady(this)
            }
        }

        val navHostFragment = supportFragmentManager
            .findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        val navController = navHostFragment.navController
        binding.bottomNav.setupWithNavController(navController)

        val savedDest = GuiStatePreferences.readNavDestinationId(this)
        binding.bottomNav.post {
            if (savedDest != navController.currentDestination?.id) {
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
                        updateBannerVisibility(monetization)
                        if (adFree) {
                            tearDownBannerAd()
                            interstitialAds.release()
                        } else if (adsConsentReady) {
                            ensureBannerAd(monetization)
                            interstitialAds.onConsentReady(this@MainActivity)
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

    /**
     * Adaptive banners must not cover publisher UI. With adjustResize + IME, the banner can
     * end up overlapping form fields — hide it while the keyboard is visible.
     */
    private fun observeImeForBanner(monetization: PlayStoreMonetization) {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val visible = insets.isVisible(WindowInsetsCompat.Type.ime())
            if (visible != imeVisible) {
                imeVisible = visible
                updateBannerVisibility(monetization)
            }
            ViewCompat.onApplyWindowInsets(view, insets)
        }
    }

    private fun updateBannerVisibility(monetization: PlayStoreMonetization) {
        val show = !monetization.adFree.value && !imeVisible
        binding.adBannerContainer.isGone = !show
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
        updateBannerVisibility(monetization)
    }

    private fun tearDownBannerAd() {
        bannerAdView?.destroy()
        binding.adBannerContainer.removeAllViews()
        bannerAdView = null
    }

    /** Called by fragments once an enrichment run has finished and its results are on screen. */
    fun onEnrichmentTaskCompleted() {
        if (!lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        interstitialAds.showAfterCompletedTask(this)
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
        interstitialAds.release()
        super.onDestroy()
    }
}
