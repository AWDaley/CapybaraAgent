package com.tervoro.capybara

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.tervoro.tal.ApprovalDecision
import com.tervoro.tal.ApprovalRequest

private val Forest = Color(0xFF0A1713)
private val Moss = Color(0xFF83D6A6)
private val Cream = Color(0xFFF2F2E8)
private val Slate = Color(0xFF16241F)
private val Muted = Color(0xFFAABBB3)
private val Amber = Color(0xFFFFC56F)

private val TervoroColors = darkColorScheme(
    primary = Moss,
    onPrimary = Forest,
    secondary = Amber,
    background = Forest,
    onBackground = Cream,
    surface = Slate,
    onSurface = Cream,
    outline = Color(0xFF476057),
    error = Color(0xFFFF9D91),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TervoroApp(
    viewModel: AgentViewModel,
    onPickModel: () -> Unit,
    onPickDocument: () -> Unit,
    onAuthenticate: ((Boolean, String?) -> Unit) -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    MaterialTheme(colorScheme = TervoroColors) {
        Surface(modifier = Modifier.fillMaxSize(), color = Forest) {
            Scaffold(
                containerColor = Forest,
                topBar = {
                    Header(
                        modelReady = state.modelReady,
                        runtimeName = state.runtimeName,
                        onPickModel = onPickModel,
                    )
                },
            ) { padding ->
                AgentScreen(
                    state = state,
                    onSend = viewModel::send,
                    onCancel = viewModel::cancelRun,
                    onPickModel = onPickModel,
                    onPickDocument = onPickDocument,
                    modifier = Modifier.padding(padding),
                )
            }
        }

        state.pendingApproval?.let { request ->
            ApprovalSheet(
                request = request,
                onApprove = {
                    onAuthenticate { approved, _ ->
                        // A cancelled/stale biometric callback may never
                        // authorize another task's pending write.
                        val decision = if (approved) ApprovalDecision.APPROVED else ApprovalDecision.DENIED
                        viewModel.resolveApproval(request.requestId, decision)
                    }
                },
                onDeny = { viewModel.resolveApproval(request.requestId, ApprovalDecision.DENIED) },
            )
        }
    }
}

@Composable
private fun Header(
    modelReady: Boolean,
    runtimeName: String,
    onPickModel: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Forest)
            .statusBarsPadding()
            .padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(42.dp)
                .background(Moss, RoundedCornerShape(13.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text("T", color = Forest, fontWeight = FontWeight.Black, fontSize = 21.sp)
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                "TERVORO",
                fontWeight = FontWeight.ExtraBold,
                letterSpacing = 2.sp,
                modifier = Modifier.semantics { heading() },
            )
            Text(
                runtimeName,
                color = Muted,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        LocalBadge(modelReady)
        IconButton(onClick = onPickModel) {
            Icon(Icons.Default.Add, contentDescription = "Import or replace local model", tint = Cream)
        }
    }
}

@Composable
private fun LocalBadge(ready: Boolean) {
    Row(
        modifier = Modifier.background(Color(0xFF142E24), CircleShape).padding(horizontal = 10.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(Modifier.size(7.dp).background(if (ready) Moss else Amber, CircleShape))
        Text(if (ready) "LOCAL" else "SETUP", color = if (ready) Moss else Amber, fontSize = 11.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun AgentScreen(
    state: AgentUiState,
    onSend: (String) -> Unit,
    onCancel: () -> Unit,
    onPickModel: () -> Unit,
    onPickDocument: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var input by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val focusManager = LocalFocusManager.current
    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) listState.animateScrollToItem(state.messages.lastIndex)
    }

    Column(
        modifier = modifier.fillMaxSize().imePadding().navigationBarsPadding(),
    ) {
        StatusCard(state, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        if (!state.modelReady) {
            ModelSetupCard(state.modelStatus, onPickModel, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
        if (state.modelReady) {
            OutlinedButton(onClick = onPickDocument, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text(state.selectedDocumentName?.let { "Document: $it" } ?: "Select text document")
            }
        }
        state.error?.let { error ->
            Text(error, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
        }

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(state.messages, key = { it.id }) { message -> MessageBubble(message) }
            if (state.isRunning && state.pendingApproval == null) {
                item { ThinkingRow(state.phase) }
            }
        }

        HorizontalDivider(color = Color(0xFF233A31))
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it.take(8_192) },
                modifier = Modifier.weight(1f),
                enabled = state.modelReady && !state.isRunning,
                placeholder = { Text(if (state.modelReady) "Ask or assign a local task…" else "Load a local model first") },
                shape = RoundedCornerShape(20.dp),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = {
                    if (input.isNotBlank()) {
                        onSend(input)
                        input = ""
                        focusManager.clearFocus()
                    }
                }),
                maxLines = 5,
            )
            IconButton(
                onClick = {
                    if (state.isRunning) {
                        onCancel()
                    } else {
                        onSend(input)
                        input = ""
                        focusManager.clearFocus()
                    }
                },
                enabled = if (state.isRunning) true else state.modelReady && input.isNotBlank(),
                modifier = Modifier.size(54.dp).background(Moss, CircleShape),
            ) {
                Icon(
                    if (state.isRunning) Icons.Default.Close else Icons.Default.Send,
                    contentDescription = if (state.isRunning) "Cancel task" else "Send task",
                    tint = Forest,
                )
            }
        }
    }
}

@Composable
private fun StatusCard(state: AgentUiState, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Slate),
        shape = RoundedCornerShape(18.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.Lock, contentDescription = null, tint = Moss, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(9.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text("TAL governed", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text(state.modelStatus, color = Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(state.phase.uppercase(), color = Amber, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                Text("${state.auditEventCount} audit events", color = Muted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun ModelSetupCard(status: String, onPickModel: () -> Unit, modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF213026))) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("On-device model required", fontWeight = FontWeight.Bold)
            Text(status, color = Muted, fontSize = 13.sp)
            Text("The model is copied into no-backup private storage. This app declares no internet permission.", color = Muted, fontSize = 12.sp)
            Button(onClick = onPickModel) { Text("Choose .litertlm model") }
        }
    }
}

@Composable
private fun MessageBubble(message: ChatMessage) {
    val isUser = message.role == MessageRole.USER
    val color = when (message.role) {
        MessageRole.USER -> Color(0xFF234E3D)
        MessageRole.AGENT -> Slate
        MessageRole.SYSTEM -> Color(0xFF1B2823)
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(if (message.role == MessageRole.SYSTEM) 1f else 0.88f)
                .background(color, RoundedCornerShape(18.dp)).padding(14.dp),
        ) {
            Text(
                when (message.role) {
                    MessageRole.USER -> "YOU"
                    MessageRole.AGENT -> "TERVORO"
                    MessageRole.SYSTEM -> "SECURITY STATE"
                },
                color = if (isUser) Moss else Amber,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp,
            )
            Spacer(Modifier.height(5.dp))
            Text(message.content, color = Cream, lineHeight = 21.sp)
        }
    }
}

@Composable
private fun ThinkingRow(phase: String) {
    Row(
        modifier = Modifier.padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        CircularProgressIndicator(Modifier.size(18.dp), color = Moss, strokeWidth = 2.dp)
        Text(phase, color = Muted, fontSize = 13.sp)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ApprovalSheet(
    request: ApprovalRequest,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDeny,
        containerColor = Slate,
        contentColor = Cream,
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 22.dp).padding(bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("Review TAL action", fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.semantics { heading() })
            Text("One-time authorization · ${request.tool.effect.name.lowercase()} effect", color = Amber, fontWeight = FontWeight.Bold)
            ApprovalField("Tool", request.tool.name)
            ApprovalField("Purpose", request.tool.description)
            ApprovalField("Arguments", request.canonicalArguments)
            ApprovalField("Manifest", request.manifestId)
            ApprovalField("Manifest hash", request.manifestHash.take(20) + "…")
            ApprovalField("State version", request.stateVersion.toString())
            ApprovalField("Expires", request.expiresAt.toString())
            Text(
                "Authentication approves only this exact typed proposal, manifest hash, state version, and expiry. It does not widen the task manifest.",
                color = Muted,
                fontSize = 12.sp,
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = onDeny, modifier = Modifier.weight(1f)) { Text("Deny") }
                Button(
                    onClick = onApprove,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Moss, contentColor = Forest),
                ) {
                    Icon(Icons.Default.Lock, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(7.dp))
                    Text("Authenticate")
                }
            }
        }
    }
}

@Composable
private fun ApprovalField(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label.uppercase(), color = Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
        Text(value, color = Cream, fontSize = 14.sp)
    }
}
