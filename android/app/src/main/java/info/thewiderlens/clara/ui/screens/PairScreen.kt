package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
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
            Spacer(Modifier.height(28.dp))
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
