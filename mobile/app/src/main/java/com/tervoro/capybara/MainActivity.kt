package com.tervoro.capybara

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

class MainActivity : FragmentActivity() {
    private val viewModel: AgentViewModel by viewModels()
    private val modelPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let(viewModel::importModel)
    }
    private val documentPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let(viewModel::selectDocument)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            TervoroApp(
                viewModel = viewModel,
                onPickModel = { modelPicker.launch(arrayOf("application/octet-stream", "*/*")) },
                onPickDocument = { documentPicker.launch(arrayOf("text/plain", "text/markdown", "application/json")) },
                onAuthenticate = ::authenticateApproval,
            )
        }
    }

    private fun authenticateApproval(onResult: (Boolean, String?) -> Unit) {
        val authenticators = BiometricManager.Authenticators.BIOMETRIC_STRONG or
            BiometricManager.Authenticators.DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) {
            onResult(false, "Strong biometric or device credential authentication is unavailable")
            return
        }

        val prompt = BiometricPrompt(
            this,
            ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    onResult(true, null)
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    onResult(false, errString.toString())
                }
            },
        )
        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Approve TAL action")
            .setSubtitle("Authenticate to authorize this one local effect")
            .setAllowedAuthenticators(authenticators)
            .setConfirmationRequired(true)
            .build()
        prompt.authenticate(promptInfo)
    }
}
