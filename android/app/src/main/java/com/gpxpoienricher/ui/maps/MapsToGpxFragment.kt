package com.gpxpoienricher.ui.maps

import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.google.android.material.snackbar.Snackbar
import com.gpxpoienricher.data.GuiStatePreferences
import com.gpxpoienricher.databinding.FragmentMapsToGpxBinding

class MapsToGpxFragment : Fragment() {

    private var _binding: FragmentMapsToGpxBinding? = null
    private val binding get() = _binding!!
    private val viewModel: MapsToGpxViewModel by viewModels()

    private val createOutput = registerForActivityResult(ActivityResultContracts.CreateDocument("application/gpx+xml")) { uri ->
        uri?.let {
            requireContext().contentResolver.takePersistableUriPermission(
                it, android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            viewModel.setOutputFile(it)
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentMapsToGpxBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val ctx = requireContext()
        binding.editUrl.setText(GuiStatePreferences.readMapsUrl(ctx))
        binding.editTrackName.setText(GuiStatePreferences.readMapsTrackName(ctx))
        when (GuiStatePreferences.readMapsMode(ctx)) {
            "cycling" -> binding.radioGroupMode.check(binding.radioCycling.id)
            "walking" -> binding.radioGroupMode.check(binding.radioWalking.id)
            else -> binding.radioGroupMode.check(binding.radioDriving.id)
        }
        GuiStatePreferences.readMapsOutputUri(ctx)?.let { s ->
            runCatching { Uri.parse(s) }.getOrNull()?.let { viewModel.setOutputFile(it) }
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
            binding.logOutput.text = lines.joinToString("\n")
            binding.logScroll.post { binding.logScroll.fullScroll(View.FOCUS_DOWN) }
        }

        viewModel.snackbar.observe(viewLifecycleOwner) { msg ->
            msg?.let {
                Snackbar.make(binding.root, it, Snackbar.LENGTH_LONG).show()
                viewModel.clearSnackbar()
            }
        }

        binding.btnBrowseOutput.setOnClickListener {
            createOutput.launch("route.gpx")
        }

        binding.btnRun.setOnClickListener {
            val url = binding.editUrl.text?.toString() ?: ""
            val mode = when (binding.radioGroupMode.checkedRadioButtonId) {
                binding.radioCycling.id -> "cycling"
                binding.radioWalking.id -> "walking"
                else -> "driving"
            }
            val trackName = binding.editTrackName.text?.toString()?.takeIf { it.isNotBlank() } ?: "Route"
            viewModel.run(url, mode, trackName)
        }

        binding.btnCancel.setOnClickListener { viewModel.cancel() }
    }

    override fun onStop() {
        val b = _binding
        if (b != null) {
            val mode = when (b.radioGroupMode.checkedRadioButtonId) {
                b.radioCycling.id -> "cycling"
                b.radioWalking.id -> "walking"
                else -> "driving"
            }
            GuiStatePreferences.writeMaps(
                requireContext(),
                b.editUrl.text?.toString() ?: "",
                mode,
                b.editTrackName.text?.toString() ?: "Route",
                viewModel.snapshotOutputUri()?.toString(),
            )
        }
        super.onStop()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
