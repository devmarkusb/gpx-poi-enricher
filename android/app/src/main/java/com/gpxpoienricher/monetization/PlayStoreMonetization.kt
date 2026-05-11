package com.gpxpoienricher.monetization

import android.app.Activity
import android.app.Application
import android.util.Log
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesUpdatedListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.gpxpoienricher.BuildConfig
import com.gpxpoienricher.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * One-time in-app “remove ads” (managed product) + local ad-free flag.
 * Create a **managed** in-app product in Play Console with id [BuildConfig.REMOVE_ADS_INAPP_PRODUCT_ID].
 */
class PlayStoreMonetization(
    private val app: Application,
) : PurchasesUpdatedListener, BillingClientStateListener {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val billingClient: BillingClient = BillingClient.newBuilder(app)
        .setListener(this)
        .enablePendingPurchases()
        .build()

    private val _adFree = MutableStateFlow(PremiumPrefs.isAdFree(app))
    val adFree: StateFlow<Boolean> = _adFree.asStateFlow()

    private val _toastMessages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val toastMessages: SharedFlow<String> = _toastMessages.asSharedFlow()

    private var removeAdsProductDetails: ProductDetails? = null

    fun start() {
        billingClient.startConnection(this)
    }

    override fun onBillingSetupFinished(result: BillingResult) {
        when (result.responseCode) {
            BillingClient.BillingResponseCode.OK -> {
                syncOwnedPurchases()
                prefetchRemoveAdsProduct()
            }
            else -> Log.w(TAG, "Billing setup: ${result.responseCode} ${result.debugMessage}")
        }
    }

    override fun onBillingServiceDisconnected() {
        billingClient.startConnection(this)
    }

    private fun prefetchRemoveAdsProduct() {
        val productId = BuildConfig.REMOVE_ADS_INAPP_PRODUCT_ID
        val params = QueryProductDetailsParams.newBuilder()
            .setProductList(
                listOf(
                    QueryProductDetailsParams.Product.newBuilder()
                        .setProductId(productId)
                        .setProductType(BillingClient.ProductType.INAPP)
                        .build(),
                ),
            )
            .build()
        billingClient.queryProductDetailsAsync(params) { billingResult, detailsList ->
            if (billingResult.responseCode != BillingClient.BillingResponseCode.OK) {
                Log.w(TAG, "queryProductDetails: ${billingResult.responseCode}")
                return@queryProductDetailsAsync
            }
            removeAdsProductDetails = detailsList?.firstOrNull { it.productId == productId }
            if (removeAdsProductDetails == null) {
                Log.w(
                    TAG,
                    "No ProductDetails for in-app id \"$productId\". Create a managed in-app product with this exact id in Play Console → Monetize → Products.",
                )
            }
        }
    }

    private fun syncOwnedPurchases() {
        billingClient.queryPurchasesAsync(
            QueryPurchasesParams.newBuilder()
                .setProductType(BillingClient.ProductType.INAPP)
                .build(),
        ) { result, purchases ->
            if (result.responseCode != BillingClient.BillingResponseCode.OK) return@queryPurchasesAsync
            val id = BuildConfig.REMOVE_ADS_INAPP_PRODUCT_ID
            val owned = purchases.any { p ->
                p.purchaseState == Purchase.PurchaseState.PURCHASED &&
                    p.products.contains(id)
            }
            applyAdFree(owned)
        }
    }

    override fun onPurchasesUpdated(result: BillingResult, purchases: MutableList<Purchase>?) {
        when (result.responseCode) {
            BillingClient.BillingResponseCode.OK ->
                purchases?.forEach { handlePurchase(it) }

            BillingClient.BillingResponseCode.USER_CANCELED -> Unit

            else -> emitToast(app.getString(R.string.billing_error_generic))
        }
    }

    private fun handlePurchase(purchase: Purchase) {
        when (purchase.purchaseState) {
            Purchase.PurchaseState.PENDING ->
                emitToast(app.getString(R.string.billing_pending))

            Purchase.PurchaseState.PURCHASED -> {
                if (!purchase.products.contains(BuildConfig.REMOVE_ADS_INAPP_PRODUCT_ID)) return
                if (!purchase.isAcknowledged) {
                    val params = AcknowledgePurchaseParams.newBuilder()
                        .setPurchaseToken(purchase.purchaseToken)
                        .build()
                    billingClient.acknowledgePurchase(params) { ackResult ->
                        if (ackResult.responseCode == BillingClient.BillingResponseCode.OK) {
                            applyAdFree(true)
                        } else {
                            emitToast(app.getString(R.string.billing_ack_failed))
                        }
                    }
                } else {
                    applyAdFree(true)
                }
            }

            else -> Unit
        }
    }

    private fun applyAdFree(value: Boolean) {
        PremiumPrefs.setAdFree(app, value)
        _adFree.value = value
    }

    private fun emitToast(msg: String) {
        scope.launch { _toastMessages.emit(msg) }
    }

    fun launchRemoveAdsFlow(activity: Activity) {
        if (_adFree.value) return
        val details = removeAdsProductDetails
        if (details == null) {
            emitToast(activity.getString(R.string.billing_store_not_ready))
            prefetchRemoveAdsProduct()
            return
        }
        val pdParams = BillingFlowParams.ProductDetailsParams.newBuilder()
            .setProductDetails(details)
            .build()
        val flowParams = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(pdParams))
            .build()
        val launchResult = billingClient.launchBillingFlow(activity, flowParams)
        if (launchResult.responseCode != BillingClient.BillingResponseCode.OK) {
            emitToast(activity.getString(R.string.billing_could_not_open_payment))
        }
    }

    /** Re-queries Play for active in-app purchases (e.g. new device or after reinstall). */
    fun restorePurchases() {
        syncOwnedPurchases()
    }

    companion object {
        private const val TAG = "PlayStoreMonetization"
    }
}
