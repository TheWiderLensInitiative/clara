package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.components.Mascot
import info.thewiderlens.clara.ui.theme.ClaraColors

@Composable
fun PairScreen(state: UiState, onPair: (String, String) -> Unit) {
    var url by rememberSaveable { mutableStateOf(state.bridgeUrl) }
    var code by rememberSaveable { mutableStateOf("") }
    var setup by rememberSaveable { mutableStateOf(false) }
    if (setup) SetupGuide { setup = false }
    Box(Modifier.fillMaxSize().background(ClaraColors.Black).safeDrawingPadding().imePadding()) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Mascot(size = 150.dp)
            Spacer(Modifier.height(18.dp))
            Text("Meet Clara", style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(8.dp))
            Text(
                "Your private assistant, running on your own computer. Connect this phone to it once.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(12.dp))
            // up here, not at the bottom, so the keyboard can't hide it
            Text(
                "New to Clara? Set up your computer first ›",
                style = MaterialTheme.typography.titleSmall, color = ClaraColors.Cyan,
                modifier = Modifier.clip(RoundedCornerShape(12.dp)).background(ClaraColors.Panel).clickable { setup = true }
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            )
            Spacer(Modifier.height(20.dp))
            OutlinedTextField(
                value = url, onValueChange = { url = it }, singleLine = true,
                label = { Text("Computer address") }, placeholder = { Text("192.168.1.20:8700") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp),
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = code, onValueChange = { code = it.filter(Char::isDigit).take(6) }, singleLine = true,
                label = { Text("Pairing code") }, placeholder = { Text("6 digits from `clara pair`") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp),
            )
            Spacer(Modifier.height(20.dp))
            if (state.busyPairing) {
                CircularProgressIndicator(color = ClaraColors.Cyan, modifier = Modifier.size(36.dp))
            } else {
                GradientButton("Connect", enabled = url.isNotBlank() && code.length == 6, modifier = Modifier.fillMaxWidth()) { onPair(url, code) }
            }
            state.error?.let {
                Spacer(Modifier.height(14.dp))
                Text(it, color = ClaraColors.Danger, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(24.dp))
            Text(
                "On your computer, run  clara pair  to get a code.",
                style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(ClaraColors.Panel).padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
    }
}

private const val SETUP_URL = "https://github.com/TheWiderLensInitiative/clara/blob/main/docs/INSTALL.md"
private const val INSTALL_CMD = "git clone https://github.com/TheWiderLensInitiative/clara ~/clara && cd ~/clara && ./install.sh"

/** For someone who installed the app first: what Clara needs on the computer and how to set it up. */
@Composable
private fun SetupGuide(onClose: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose, properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
        Column(
            Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(24.dp)).background(ClaraColors.Panel)
                .verticalScroll(rememberScrollState()).padding(22.dp),
        ) {
            Text("Set up Clara on your computer", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            Text(
                "Clara's brain runs on your own PC, not in the cloud. This app is how you talk to her. You'll need:",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted,
            )
            Spacer(Modifier.height(10.dp))
            listOf(
                "A Linux PC (Ubuntu 24.04 or newer)",
                "An NVIDIA graphics card with 12 GB of memory or more",
                "16 GB of RAM and 40 GB of free disk space",
            ).forEach { Text("•  $it", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 2.dp)) }
            Spacer(Modifier.height(14.dp))
            Text("On the computer, open a terminal and run:", style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
            Spacer(Modifier.height(8.dp))
            Text(
                INSTALL_CMD, style = MaterialTheme.typography.bodySmall.copy(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace),
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(ClaraColors.Black).padding(12.dp),
            )
            Text(
                "Copy", style = MaterialTheme.typography.labelLarge, color = ClaraColors.Cyan,
                modifier = Modifier.align(Alignment.End).clip(RoundedCornerShape(8.dp)).clickable {
                    context.getSystemService(android.content.ClipboardManager::class.java)
                        .setPrimaryClip(android.content.ClipData.newPlainText("Clara install command", INSTALL_CMD))
                    android.widget.Toast.makeText(context, "Copied", android.widget.Toast.LENGTH_SHORT).show()
                }.padding(horizontal = 10.dp, vertical = 8.dp),
            )
            Text(
                "It takes 20 to 40 minutes. At the end it shows a QR code for this app, a computer address and a pairing code. " +
                    "Enter those here to connect.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted,
            )
            Spacer(Modifier.height(18.dp))
            GradientButton("Send to my computer", modifier = Modifier.fillMaxWidth()) {
                val text = "Set up Clara, my private AI assistant, on this computer: https://clara.thewiderlens.info\n\nIn a terminal, run:\n$INSTALL_CMD\n\nStep-by-step guide: $SETUP_URL"
                val send = android.content.Intent(android.content.Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(android.content.Intent.EXTRA_SUBJECT, "Set up Clara on my computer")
                    .putExtra(android.content.Intent.EXTRA_TEXT, text)
                runCatching { context.startActivity(android.content.Intent.createChooser(send, "Send the setup link")) }
            }
            Spacer(Modifier.height(4.dp))
            androidx.compose.material3.TextButton(onClick = {
                runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(SETUP_URL))) }
            }, modifier = Modifier.fillMaxWidth()) { Text("Open the setup guide", color = ClaraColors.Cyan) }
            androidx.compose.material3.TextButton(onClick = onClose, modifier = Modifier.fillMaxWidth()) { Text("I've already set it up", color = ClaraColors.Muted) }
        }
    }
}
