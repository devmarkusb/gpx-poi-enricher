package com.gpxpoienricher.ui.split

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
import com.gpxpoienricher.databinding.FragmentSplitBinding

class SplitFragment : Fragment() {

    private var _binding: FragmentSplitBinding? = null
    private val binding get() = _binding!!
    private val viewModel: SplitViewModel by viewModels()

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
        _binding = FragmentSplitBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val ctx = requireContext()
        binding.editSegments.setText(GuiStatePreferences.readSplitSegments(ctx))
        GuiStatePreferences.readSplitInputUri(ctx)?.let { s ->
            runCatching { Uri.parse(s) }.getOrNull()?.let { viewModel.setInputFile(it) }
        }
        GuiStatePreferences.readSplitOutputUri(ctx)?.let { s ->
            runCatching { Uri.parse(s) }.getOrNull()?.let { viewModel.setOutputFile(it) }
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

        binding.btnBrowseInput.setOnClickListener {
            openInput.launch(arrayOf("application/gpx+xml", "*/*"))
        }

        binding.btnBrowseOutput.setOnClickListener {
            createOutput.launch("split_waypoints.gpx")
        }

        binding.btnRun.setOnClickListener {
            val segments = binding.editSegments.text?.toString()?.toIntOrNull() ?: 10
            viewModel.run(segments)
        }

        binding.btnCancel.setOnClickListener { viewModel.cancel() }
    }

    override fun onStop() {
        val b = _binding
        if (b != null) {
            GuiStatePreferences.writeSplit(
                requireContext(),
                viewModel.snapshotInputUri()?.toString(),
                viewModel.snapshotOutputUri()?.toString(),
                b.editSegments.text?.toString() ?: "10",
            )
        }
        super.onStop()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
