package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
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
import info.thewiderlens.clara.data.SavedLogin
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.theme.ClaraColors

private val NAME_OK = Regex("^[A-Za-z0-9_-]{1,64}$")

/**
 * Saved logins. Write-only: you can add and remove logins, and see names/sites/usernames,
 * but no password is ever sent back to this phone — and Clara never sees them at all.
 */
@Composable
fun PasswordsPage(state: UiState, onRefresh: () -> Unit, onSave: (String, String, String, String) -> Unit, onDelete: (String) -> Unit, onBack: () -> Unit,
                  prefill: Pair<String, String>? = null) {
    LaunchedEffect(Unit) { onRefresh() }
    // Opened from a connector ("Use with a saved login"): the add form starts with that service's name and sign-in page
    var adding by remember { mutableStateOf(prefill != null && state.logins.none { it.name == prefill.first.replace(' ', '-') }) }
    var confirmDelete by remember { mutableStateOf<SavedLogin?>(null) }
    PageScaffold("Passwords", onBack) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
                    .border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🔐", style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.width(12.dp))
                Text(
                    "Your passwords are stored only on this phone, locked by its security chip. Clara just picks a login by name — " +
                        "you confirm each sign-in with your fingerprint, and she never sees the password.",
                    style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Saved logins", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, modifier = Modifier.weight(1f))
                TextButton(onClick = { adding = true }) { Icon(Icons.Filled.Add, null, tint = ClaraColors.Cyan); Text(" Add login", color = ClaraColors.Cyan) }
            }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.logins.isEmpty()) item {
                    Text("No saved logins yet. Add one and ask Clara to sign in, e.g. “log in to GitHub and check my notifications”.",
                        color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 20.dp))
                }
                items(state.logins, key = { it.name }) { l ->
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel)
                            .border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)).padding(start = 14.dp, top = 10.dp, bottom = 10.dp, end = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(38.dp).clip(RoundedCornerShape(10.dp)).background(ClaraColors.Raised), contentAlignment = Alignment.Center) {
                            Text(l.name.take(1).uppercase(), style = MaterialTheme.typography.titleMedium, color = ClaraColors.Cyan)
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(l.name, style = MaterialTheme.typography.bodyLarge)
                            Text("${l.username ?: ""} · ${l.site?.removePrefix("https://")?.removePrefix("http://")?.substringBefore('/') ?: ""}",
                                style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                            Text("Password  ••••••••", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                        }
                        IconButton(onClick = { confirmDelete = l }) { Icon(Icons.Filled.Delete, "Delete", tint = ClaraColors.Muted) }
                    }
                }
            }
        }
    }
    if (adding) AddLoginDialog(onDismiss = { adding = false }, startName = prefill?.first?.replace(' ', '-') ?: "",
        startUrl = prefill?.second?.ifBlank { null } ?: "https://") { n, u, user, pw -> onSave(n, u, user, pw); adding = false }
    confirmDelete?.let { l ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null }, containerColor = ClaraColors.Panel,
            title = { Text("Delete “${l.name}”?") },
            text = { Text("Clara won't be able to sign in to this site anymore.") },
            confirmButton = { TextButton(onClick = { onDelete(l.name); confirmDelete = null }) { Text("Delete", color = ClaraColors.Danger) } },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
}

@Composable
private fun AddLoginDialog(onDismiss: () -> Unit, startName: String = "", startUrl: String = "https://", onSave: (String, String, String, String) -> Unit) {
    var name by remember { mutableStateOf(startName) }
    var url by remember { mutableStateOf(startUrl) }
    var user by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }
    val nameOk = NAME_OK.matches(name)
    val ok = nameOk && url.length > 10 && url.startsWith("http") && user.isNotBlank() && pw.isNotEmpty()
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = ClaraColors.Panel,
        title = { Text("Add a login") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.replace(' ', '-') }, label = { Text("Name (e.g. GitHub)") }, singleLine = true,
                    isError = name.isNotEmpty() && !nameOk, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(url, { url = it.trim() }, label = { Text("Login page") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
                OutlinedTextField(user, { user = it }, label = { Text("Username or email") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(pw, { pw = it }, label = { Text("Password") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
                Text("Saved only on this phone. Clara sees the name, site and username — never the password. Sign-ins only work on this exact site.",
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
            }
        },
        confirmButton = { TextButton(enabled = ok, onClick = { onSave(name, url, user, pw) }) { Text("Save", color = if (ok) ClaraColors.Cyan else ClaraColors.Muted) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = ClaraColors.Muted) } },
    )
}
