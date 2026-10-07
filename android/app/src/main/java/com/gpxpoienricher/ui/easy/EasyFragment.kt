package com.gpxpoienricher.ui.easy

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.MainActivity
import com.gpxpoienricher.R
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.FragmentEasyBinding

class EasyFragment : Fragment() {

    private var _binding: FragmentEasyBinding? = null
    private val binding get() = _binding!!
    private val vm: EasyViewModel by viewModels()

    private var profileFromPrefsApplied = false
    private var wasRunning = false

    private var pendingGenerate: (() -> Unit)? = null

    private val requestWritePermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            pendingGenerate?.invoke()
        } else {
            Snackbar.make(binding.root, R.string.msg_storage_permission_denied, Snackbar.LENGTH_LONG).show()
        }
        pendingGenerate = null
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentEasyBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        profileFromPrefsApplied = false
        val ctx = requireContext()
        binding.editPointInput.setText(GuiStatePreferences.readEasyPointInput(ctx))
        binding.searchModeGroup.check(
            if (GuiStatePreferences.readEasyPointMode(ctx)) binding.radioPointSearch.id else binding.radioTrackSearch.id,
        )
        updateSearchMode()
        binding.searchModeGroup.setOnCheckedChangeListener { _, _ -> updateSearchMode() }
        binding.editUrl.setText(GuiStatePreferences.readEasyPrimaryUrl(ctx))
        binding.editExtraUrls.setText(GuiStatePreferences.readEasyExtraUrls(ctx))
        binding.editMilestoneParts.setText(GuiStatePreferences.readEasyMilestoneParts(ctx).toString())

        vm.profiles.observe(viewLifecycleOwner) { profiles ->
            val keepId = vm.profileIdAtSpinnerIndex(binding.spinnerProfile.selectedItemPosition)
                .takeIf { binding.spinnerProfile.adapter != null }
                ?: if (!profileFromPrefsApplied) GuiStatePreferences.readEasyProfileId(ctx) else null
            if (!profileFromPrefsApplied) profileFromPrefsApplied = true
            val adapter = ArrayAdapter(
                requireContext(),
                android.R.layout.simple_spinner_item,
                profiles.map { it.description },
            )
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            binding.spinnerProfile.adapter = adapter
            if (profiles.isEmpty()) return@observe
            val idx = when {
                !keepId.isNullOrBlank() -> profiles.indexOfFirst { it.id == keepId }
                else -> 0
            }.let { if (it >= 0) it else 0 }
            binding.spinnerProfile.setSelection(idx.coerceAtMost(profiles.lastIndex))
        }

        vm.isRunning.observe(viewLifecycleOwner) { running ->
            binding.radioTrackSearch.isEnabled = !running && vm.canResume.value != true
            binding.radioPointSearch.isEnabled = !running && vm.canResume.value != true
            binding.btnGenerate.isEnabled = !running
            binding.btnCancel.isEnabled = running
            binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE

            val finishedRun = wasRunning && !running &&
                vm.result.value != null && vm.canResume.value != true
            if (finishedRun) {
                (activity as? MainActivity)?.onEnrichmentTaskCompleted()
            }
            wasRunning = running
        }

        vm.logLines.observe(viewLifecycleOwner) { lines ->
            val b = _binding ?: return@observe
            b.logOutput.text = lines.joinToString("\n")
            b.logScroll.post {
                _binding?.logScroll?.fullScroll(View.FOCUS_DOWN)
            }
        }

        vm.result.observe(viewLifecycleOwner) { result ->
            if (result == null) {
                binding.cardResults.visibility = View.GONE
                binding.labelMilestoneSection.visibility = View.GONE
                binding.textMilestonePaths.visibility = View.GONE
                return@observe
            }
            binding.cardResults.visibility = View.VISIBLE
            val reusedNote = if (result.trackReused) "  (reused)" else ""
            binding.textTrackFile.visibility = if (result.trackPath.isBlank()) View.GONE else View.VISIBLE
            binding.textTrackFile.text = result.trackPath + reusedNote
            binding.textPoiFile.text = "${result.poiPath}  (${result.poiCount} POI(s))"

            if (result.milestonePaths.isNotEmpty()) {
                binding.labelMilestoneSection.visibility = View.VISIBLE
                binding.textMilestonePaths.visibility = View.VISIBLE
                binding.textMilestonePaths.text = result.milestonePaths.joinToString("\n")
            } else {
                binding.labelMilestoneSection.visibility = View.GONE
                binding.textMilestonePaths.visibility = View.GONE
            }

            if (result.alternateFullPaths.isNotEmpty()) {
                binding.labelAlternateFull.visibility = View.VISIBLE
                binding.textAlternatePaths.visibility = View.VISIBLE
                binding.textAlternatePaths.text = result.alternateFullPaths.joinToString("\n")
            } else {
                binding.labelAlternateFull.visibility = View.GONE
                binding.textAlternatePaths.visibility = View.GONE
            }

            if (result.detourResults.isNotEmpty()) {
                binding.labelDetourSection.visibility = View.VISIBLE
                binding.textDetourFiles.visibility = View.VISIBLE
                binding.textDetourFiles.text = result.detourResults.joinToString("\n\n") { d ->
                    "${d.trackPath}\n  → ${d.poiPath}  (${d.poiCount} POI(s))"
                }
            } else {
                binding.labelDetourSection.visibility = View.GONE
                binding.textDetourFiles.visibility = View.GONE
            }
        }

        vm.snackbar.observe(viewLifecycleOwner) { msg ->
            if (msg != null) {
                Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
                vm.clearSnackbar()
            }
        }

        vm.canResume.observe(viewLifecycleOwner) { resume ->
            binding.radioTrackSearch.isEnabled = !resume && vm.isRunning.value != true
            binding.radioPointSearch.isEnabled = !resume && vm.isRunning.value != true
            binding.btnGenerate.text = getString(
                if (resume) R.string.btn_resume_enrichment else R.string.btn_generate,
            )
        }

        binding.btnBatterySettings.setOnClickListener {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }

        binding.btnGenerate.setOnClickListener {
            val pointMode = binding.radioPointSearch.isChecked
            val url = (if (pointMode) binding.editPointInput else binding.editUrl).text?.toString() ?: ""
            val extras = binding.editExtraUrls.text?.toString() ?: ""
            val parts = binding.editMilestoneParts.text?.toString()?.trim()?.toIntOrNull()?.coerceIn(0, 9999) ?: 0
            val profileIx = binding.spinnerProfile.selectedItemPosition
            val run = {
                val legacyOk = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ||
                    ContextCompat.checkSelfPermission(
                        requireContext(),
                        Manifest.permission.WRITE_EXTERNAL_STORAGE,
                    ) == PackageManager.PERMISSION_GRANTED
                vm.generate(url, extras, profileIx, parts, legacyStorageGranted = legacyOk, pointMode = pointMode)
            }
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q &&
                ContextCompat.checkSelfPermission(
                    requireContext(),
                    Manifest.permission.WRITE_EXTERNAL_STORAGE,
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                pendingGenerate = run
                if (shouldShowRequestPermissionRationale(Manifest.permission.WRITE_EXTERNAL_STORAGE)) {
                    Snackbar.make(binding.root, R.string.msg_storage_permission_for_downloads, Snackbar.LENGTH_LONG)
                        .setAction(android.R.string.ok) {
                            requestWritePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                        }
                        .show()
                } else {
                    requestWritePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                }
            } else {
                run()
            }
        }

        binding.btnCancel.setOnClickListener { vm.cancel() }
    }

    private fun updateSearchMode() {
        val point = binding.radioPointSearch.isChecked
        binding.routeInputCard.visibility = if (point) View.GONE else View.VISIBLE
        binding.pointInputCard.visibility = if (point) View.VISIBLE else View.GONE
        binding.layoutMilestoneParts.visibility = if (point) View.GONE else View.VISIBLE
        binding.backgroundNoticeCard.visibility = if (point) View.GONE else View.VISIBLE
        binding.pointRadiusHint.visibility = if (point) View.VISIBLE else View.GONE
    }

    override fun onResume() {
        super.onResume()
        vm.reloadProfiles()
    }

    override fun onStop() {
        val b = _binding
        if (b != null) {
            val ctx = requireContext()
            val pid = vm.profileIdAtSpinnerIndex(b.spinnerProfile.selectedItemPosition)
            val milestoneParts =
                b.editMilestoneParts.text?.toString()?.trim()?.toIntOrNull()?.coerceIn(0, 9999) ?: 0
            GuiStatePreferences.writeEasy(
                ctx,
                b.editUrl.text?.toString() ?: "",
                b.editExtraUrls.text?.toString() ?: "",
                pid,
                milestoneParts,
                b.radioPointSearch.isChecked,
                b.editPointInput.text?.toString() ?: "",
            )
        }
        super.onStop()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
