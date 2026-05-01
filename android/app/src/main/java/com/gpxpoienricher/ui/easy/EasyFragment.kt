package com.gpxpoienricher.ui.easy

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.FragmentEasyBinding

class EasyFragment : Fragment() {

    private var _binding: FragmentEasyBinding? = null
    private val binding get() = _binding!!
    private val vm: EasyViewModel by viewModels()

    private var profileFromPrefsApplied = false

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
            binding.btnGenerate.isEnabled = !running
            binding.btnCancel.isEnabled = running
            binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE
        }

        vm.logLines.observe(viewLifecycleOwner) { lines ->
            binding.logOutput.text = lines.joinToString("\n")
            binding.logScroll.post { binding.logScroll.fullScroll(View.FOCUS_DOWN) }
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

        binding.btnGenerate.setOnClickListener {
            val url = binding.editUrl.text?.toString() ?: ""
            val extras = binding.editExtraUrls.text?.toString() ?: ""
            val parts = binding.editMilestoneParts.text?.toString()?.trim()?.toIntOrNull()?.coerceIn(0, 9999) ?: 0
            vm.generate(url, extras, binding.spinnerProfile.selectedItemPosition, parts)
        }

        binding.btnCancel.setOnClickListener { vm.cancel() }
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
            )
        }
        super.onStop()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
