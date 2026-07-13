package com.gpxpoienricher.ui.enricher

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.FragmentEnricherBinding
import com.gpxpoienricher.R

class EnricherFragment : Fragment() {

    private var _binding: FragmentEnricherBinding? = null
    private val binding get() = _binding!!
    private val viewModel: EnricherViewModel by viewModels()

    private var profileFromPrefsApplied = false

    private val openInput = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            requireContext().contentResolver.takePersistableUriPermission(
                it, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            viewModel.setInputFile(it)
        }
    }

    private val createOutput = registerForActivityResult(ActivityResultContracts.CreateDocument("application/gpx+xml")) { uri ->
        uri?.let {
            requireContext().contentResolver.takePersistableUriPermission(
                it, android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            viewModel.setOutputFile(it)
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentEnricherBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        profileFromPrefsApplied = false
        val ctx = requireContext()
        binding.editMaxKm.setText(GuiStatePreferences.readEnricherMaxKm(ctx))
        binding.editSampleKm.setText(GuiStatePreferences.readEnricherSampleKm(ctx))
        GuiStatePreferences.readEnricherInputUri(ctx)?.let { s ->
            runCatching { Uri.parse(s) }.getOrNull()?.let { viewModel.setInputFile(it) }
        }
        GuiStatePreferences.readEnricherOutputUri(ctx)?.let { s ->
            runCatching { Uri.parse(s) }.getOrNull()?.let { viewModel.setOutputFile(it) }
        }

        viewModel.profiles.observe(viewLifecycleOwner) { profiles ->
            val keepId = viewModel.profileIdAtSpinnerIndex(binding.profileSpinner.selectedItemPosition)
                .takeIf { binding.profileSpinner.adapter != null }
                ?: if (!profileFromPrefsApplied) GuiStatePreferences.readEnricherProfileId(ctx) else null
            if (!profileFromPrefsApplied) profileFromPrefsApplied = true
            val names = profiles.map { it.description }
            binding.profileSpinner.adapter = ArrayAdapter(
                requireContext(), android.R.layout.simple_spinner_item, names
            ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
            if (profiles.isEmpty()) return@observe
            val idx = when {
                !keepId.isNullOrBlank() -> profiles.indexOfFirst { it.id == keepId }
                else -> 0
            }.let { if (it >= 0) it else 0 }
            binding.profileSpinner.setSelection(idx.coerceAtMost(profiles.lastIndex))
        }

        viewModel.inputName.observe(viewLifecycleOwner) { name ->
            binding.inputFileName.text = name ?: "No file selected"
        }

        viewModel.outputName.observe(viewLifecycleOwner) { name ->
            binding.outputFileName.text = name ?: "No file selected"
        }

        viewModel.isRunning.observe(viewLifecycleOwner) { running ->
            binding.btnRun.isEnabled = !running
            binding.btnCancel.isEnabled = running
            binding.progressBar.visibility = if (running) View.VISIBLE else View.GONE
        }

        viewModel.logLines.observe(viewLifecycleOwner) { lines ->
            val b = _binding ?: return@observe
            b.logOutput.text = lines.joinToString("\n")
            b.logScroll.post {
                _binding?.logScroll?.fullScroll(View.FOCUS_DOWN)
            }
        }

        viewModel.snackbar.observe(viewLifecycleOwner) { msg ->
            msg?.let {
                Snackbar.make(binding.root, it, Snackbar.LENGTH_LONG).show()
                viewModel.clearSnackbar()
            }
        }

        viewModel.canResume.observe(viewLifecycleOwner) { resume ->
            binding.btnRun.text = getString(
                if (resume) R.string.btn_resume_enrichment else R.string.btn_run,
            )
        }

        binding.btnBatterySettings.setOnClickListener {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }

        binding.btnBrowseInput.setOnClickListener {
            openInput.launch(arrayOf("application/gpx+xml", "*/*"))
        }

        binding.btnBrowseOutput.setOnClickListener {
            createOutput.launch("output.gpx")
        }

        binding.btnRun.setOnClickListener {
            val maxKm = binding.editMaxKm.text?.toString()?.toDoubleOrNull()
            val sampleKm = binding.editSampleKm.text?.toString()?.toDoubleOrNull()
            viewModel.run(binding.profileSpinner.selectedItemPosition, maxKm, sampleKm)
        }

        binding.btnCancel.setOnClickListener { viewModel.cancel() }
    }

    override fun onResume() {
        super.onResume()
        viewModel.reloadProfiles()
    }

    override fun onStop() {
        val b = _binding
        if (b != null) {
            val ctx = requireContext()
            GuiStatePreferences.writeEnricher(
                ctx,
                viewModel.snapshotInputUri()?.toString(),
                viewModel.snapshotOutputUri()?.toString(),
                viewModel.profileIdAtSpinnerIndex(b.profileSpinner.selectedItemPosition),
                b.editMaxKm.text?.toString() ?: "",
                b.editSampleKm.text?.toString() ?: "",
            )
        }
        super.onStop()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
