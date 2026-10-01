package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.ApiService
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors

private val AUTH = listOf("bearer" to "Bearer token", "header" to "Header", "query" to "Query parameter", "basic" to "Username + password")
private val POLICY = listOf("ask" to "Ask every time", "trust" to "Can be allowed once approved", "never" to "Read-only")

/** Saved API keys. Write-only: the phone can add and remove keys, never read them back. Clara never sees them at all. */
@Composable
fun ApiKeysPage(state: UiState, onRefresh: () -> Unit, onSave: (String, String, String, String, String, String, String) -> Unit,
                onDelete: (String) -> Unit, onBack: () -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    var adding by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<ApiService?>(null) }
    PageScaffold("API keys", onBack) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
                    .border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🔌", style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.width(12.dp))
                Text(
                    "Clara can use any web API through your computer without ever seeing the key. Each key only goes to its own " +
                        "service, and you approve how she uses it.",
                    style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Services", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, modifier = Modifier.weight(1f))
                TextButton(onClick = { adding = true }) { Icon(Icons.Filled.Add, null, tint = ClaraColors.Cyan); Text(" Add API key", color = ClaraColors.Cyan) }
            }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.apis.isEmpty()) item {
                    Text("No API keys yet. Add one, then ask Clara to use it — e.g. “use my weather API to get tomorrow's forecast”.",
                        color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 20.dp))
                }
                items(state.apis, key = { it.name }) { a ->
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel)
                            .border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)).padding(start = 14.dp, top = 10.dp, bottom = 10.dp, end = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(38.dp).clip(RoundedCornerShape(10.dp)).background(ClaraColors.Raised), contentAlignment = Alignment.Center) {
                            Text(a.name.take(1).uppercase(), style = MaterialTheme.typography.titleMedium, color = ClaraColors.Magenta)
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(a.name, style = MaterialTheme.typography.bodyLarge)
                            Text(a.baseUrl.removePrefix("https://"), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                            Text("Key  ••••••••  · ${POLICY.firstOrNull { it.first == a.writePolicy }?.second ?: a.writePolicy}",
                                style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                        }
                        IconButton(onClick = { confirm = a }) { Icon(Icons.Filled.Delete, "Delete", tint = ClaraColors.Muted) }
                    }
                }
            }
        }
    }
    if (adding) AddApiDialog(onDismiss = { adding = false }) { n, u, t, an, k, notes, p -> onSave(n, u, t, an, k, notes, p); adding = false }
    confirm?.let { a ->
        AlertDialog(
            onDismissRequest = { confirm = null }, containerColor = ClaraColors.Panel,
            title = { Text("Remove “${a.name}”?") }, text = { Text("The key is deleted from your computer and Clara can't use this service anymore.") },
            confirmButton = { TextButton(onClick = { onDelete(a.name); confirm = null }) { Text("Remove", color = ClaraColors.Danger) } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
}

@Composable
private fun Chips(options: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        options.forEach { (value, label) ->
            Text(label, style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.clip(RoundedCornerShape(12.dp))
                    .then(if (value == selected) Modifier.background(ClaraBrush.bubble) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(12.dp)))
                    .clickable { onPick(value) }.padding(horizontal = 10.dp, vertical = 7.dp))
        }
    }
}

@Composable
private fun AddApiDialog(onDismiss: () -> Unit, onSave: (String, String, String, String, String, String, String) -> Unit) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("https://") }
    var auth by remember { mutableStateOf("bearer") }
    var authName by remember { mutableStateOf("") }
    var key by remember { mutableStateOf("") }
    var user by remember { mutableStateOf("") }
    var notes by remember { mutableStateOf("") }
    var policy by remember { mutableStateOf("ask") }
    val needsName = auth == "header" || auth == "query"
    val secret = if (auth == "basic") "$user:$key" else key
    val ok = Regex("^[A-Za-z0-9_-]{1,40}$").matches(name) && url.startsWith("https://") && url.length > 12 &&
        key.isNotEmpty() && (!needsName || authName.isNotBlank()) && (auth != "basic" || user.isNotBlank())
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = ClaraColors.Panel,
        title = { Text("Add an API key") },
        text = {
            Column(Modifier.heightIn(max = 520.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.replace(' ', '-') }, label = { Text("Name (e.g. openweather)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(url, { url = it.trim() }, label = { Text("API base URL") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
                Text("How does it take the key?", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                Chips(AUTH, auth) { auth = it }
                if (needsName) OutlinedTextField(authName, { authName = it.trim() },
                    label = { Text(if (auth == "header") "Header name (e.g. X-API-Key)" else "Parameter name (e.g. appid)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                if (auth == "basic") OutlinedTextField(user, { user = it }, label = { Text("Username") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(key, { key = it }, label = { Text(if (auth == "basic") "Password" else "API key") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                Text("Changes (sending, posting, deleting)", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                Chips(POLICY, policy) { policy = it }
                OutlinedTextField(notes, { notes = it }, label = { Text("Notes for Clara (optional): what it's for, docs link") }, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = { TextButton(enabled = ok, onClick = { onSave(name, url.trimEnd('/'), auth, authName, secret, notes, policy) }) {
            Text("Save", color = if (ok) ClaraColors.Cyan else ClaraColors.Muted) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = ClaraColors.Muted) } },
    )
}
