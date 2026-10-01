package info.thewiderlens.clara.ui.screens

import info.thewiderlens.clara.R
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.Image
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.Connector
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.theme.ClaraColors

private val CATEGORY_ORDER = listOf("Email & calendar", "Messaging", "Files & notes", "Work", "Music & home")
private val LOGOS = mapOf(   // official brand logos (Simple Icons CC0 / official files), see res/drawable/ic_brand_*.xml
    "google" to R.drawable.ic_brand_google, "microsoft" to R.drawable.ic_brand_microsoft, "dropbox" to R.drawable.ic_brand_dropbox,
    "notion" to R.drawable.ic_brand_notion, "todoist" to R.drawable.ic_brand_todoist, "github" to R.drawable.ic_brand_github,
    "slack" to R.drawable.ic_brand_slack, "discord" to R.drawable.ic_brand_discord, "telegram" to R.drawable.ic_brand_telegram,
    "spotify" to R.drawable.ic_brand_spotify, "homeassistant" to R.drawable.ic_brand_homeassistant,
    "x" to R.drawable.ic_brand_x, "meta" to R.drawable.ic_brand_facebook,
)

/** The service's logo on a white tile, like an app icon (keeps dark logos like GitHub and Notion visible). */
@Composable
fun BrandTile(provider: String, size: androidx.compose.ui.unit.Dp = 40.dp) {
    Box(Modifier.size(size).clip(RoundedCornerShape(size * 0.26f)).background(Color.White), contentAlignment = Alignment.Center) {
        val logo = LOGOS[provider]
        if (logo != null) Image(painterResource(logo), null, Modifier.size(size * 0.62f))
        else Text("🔌")
    }
}

private val OK = Color(0xFF34D399)

/** Accounts Clara can use on the user's behalf. Logins stay encrypted on the PC; Clara only gets results. */
@Composable
fun ConnectorsPage(
    state: UiState, onRefresh: () -> Unit, onSaveClient: (String, String, String) -> Unit, onSaveToken: (String, Map<String, String>) -> Unit,
    onConnect: (String) -> Unit, onDisconnect: (String, Boolean) -> Unit, onPolicy: (String, String, String) -> Unit, onBack: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    var open by remember { mutableStateOf<String?>(null) }
    PageScaffold("Connectors", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val n = state.connectors.count { it.connected }
            Text("Let Clara use your accounts. Your logins stay encrypted on your computer and Clara only ever sees results. " +
                "Anything that sends, posts or changes something shows you a preview to approve first." + if (n > 0) "  $n connected." else "",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
            if (state.connectors.isEmpty()) Text("Loading…", color = ClaraColors.Muted)
            val groups = state.connectors.groupBy { it.category }
            (CATEGORY_ORDER + (groups.keys - CATEGORY_ORDER.toSet())).forEach { cat ->
                val list = groups[cat] ?: return@forEach
                Text(cat, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, modifier = Modifier.padding(top = 10.dp))
                list.sortedByDescending { it.connected }.forEach { c ->
                    ConnectorCard(c, state, open == c.provider, { open = if (open == c.provider) null else c.provider },
                        onSaveClient, onSaveToken, onConnect, onDisconnect, onPolicy)
                }
            }
            Text("Not possible yet: posting to TikTok and Instagram (their APIs need a business review). Clara makes the videos and you share them from the player.",
                style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted, modifier = Modifier.padding(top = 8.dp))
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun ConnectorCard(
    c: Connector, state: UiState, expanded: Boolean, onToggle: () -> Unit,
    onSaveClient: (String, String, String) -> Unit, onSaveToken: (String, Map<String, String>) -> Unit,
    onConnect: (String) -> Unit, onDisconnect: (String, Boolean) -> Unit, onPolicy: (String, String, String) -> Unit,
) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
        .border(1.dp, if (c.connected) OK.copy(alpha = 0.5f) else ClaraColors.Line, RoundedCornerShape(18.dp))) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            BrandTile(c.provider)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.titleMedium)
                Text(if (c.connected) c.account.ifBlank { "Connected" } else c.services.joinToString(" · "),
                    style = MaterialTheme.typography.labelMedium, color = if (c.connected) OK else ClaraColors.Muted, maxLines = 1)
            }
            Text(if (c.connected) "●" else if (expanded) "▾" else "Set up ›", color = if (c.connected) OK else ClaraColors.Cyan,
                style = MaterialTheme.typography.labelMedium)
        }
        AnimatedVisibility(expanded) {
            Column(Modifier.padding(start = 14.dp, end = 14.dp, bottom = 14.dp)) {
                when {
                    c.connected -> ConnectedPanel(c, onDisconnect, onPolicy)
                    c.kind == "token" -> TokenSetup(c, onSaveToken)
                    else -> OAuthSetup(c, state, onSaveClient, onConnect, onDisconnect)
                }
            }
        }
    }
}

@Composable
private fun ConnectedPanel(c: Connector, onDisconnect: (String, Boolean) -> Unit, onPolicy: (String, String, String) -> Unit) {
    Text("Clara can use: " + c.services.joinToString(", ") + ". Reading is free; sending, posting and changes ask you first.",
        style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
    Spacer(Modifier.height(8.dp))
    if (c.provider == "google") {
        PolicySwitch("Add calendar events without asking", c.policy["calendar_add"] == "trust") { onPolicy(c.provider, "calendar_add", if (it) "trust" else "ask") }
        Text("Emails, invites, YouTube posts, changes and deletions still ask.", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
    } else {
        PolicySwitch("Let Clara act without asking", c.policy["writes"] == "trust") { onPolicy(c.provider, "writes", if (it) "trust" else "ask") }
        Text(if (c.provider == "homeassistant" || c.provider == "spotify") "Handy for lights and music."
             else "Only turn this on if you're comfortable with Clara sending and changing things here on her own.",
            style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
    }
    Spacer(Modifier.height(8.dp))
    OutlinedButton(onClick = { onDisconnect(c.provider, false) }, shape = RoundedCornerShape(14.dp)) { Text("Disconnect", color = ClaraColors.Danger) }
}

@Composable
private fun PolicySwitch(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = ClaraColors.Violet))
    }
}

@Composable
private fun Steps(c: Connector) {
    val context = LocalContext.current
    c.steps.forEachIndexed { i, step ->
        Row(Modifier.padding(vertical = 4.dp)) {
            Text("${i + 1}.", color = ClaraColors.Cyan, modifier = Modifier.width(22.dp))
            SelectionContainer { Text(step, style = MaterialTheme.typography.bodySmall) }   // long-press to copy the redirect URI
        }
    }
    c.setupUrl?.let { url ->
        TextButton(onClick = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } }) {
            Text("Open ${Uri.parse(url).host?.removePrefix("www.")}", color = ClaraColors.Cyan)
        }
    }
}

@Composable
private fun TokenSetup(c: Connector, onSave: (String, Map<String, String>) -> Unit) {
    val values = remember(c.provider) { mutableStateMapOf<String, String>() }
    Steps(c)
    c.fields.forEach { f ->
        OutlinedTextField(values[f.key] ?: "", { values[f.key] = it.trim() }, singleLine = true, label = { Text(f.label) },
            visualTransformation = if (f.key == "token") PasswordVisualTransformation() else VisualTransformation.None,
            modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp), shape = RoundedCornerShape(14.dp))
    }
    Spacer(Modifier.height(8.dp))
    GradientButton("Connect ${c.name}", enabled = c.fields.all { (values[it.key] ?: "").length > 5 }, modifier = Modifier.fillMaxWidth()) {
        onSave(c.provider, values.toMap())
    }
    Text("Clara checks it works before saving.", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
}

@Composable
private fun OAuthSetup(c: Connector, state: UiState, onSaveClient: (String, String, String) -> Unit, onConnect: (String) -> Unit,
                       onDisconnect: (String, Boolean) -> Unit) {
    val context = LocalContext.current
    var editing by remember(c.hasClient) { mutableStateOf(!c.hasClient) }
    var id by remember { mutableStateOf("") }
    var secret by remember { mutableStateOf("") }
    if (editing) {
        Text("One-time setup: ${c.name} needs your own free app, so this stays private to you.", style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(6.dp))
        Steps(c)
        OutlinedTextField(id, { id = it.trim() }, singleLine = true, label = { Text(if (c.provider == "dropbox") "App key" else "Client ID") },
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp))
        if (c.needsSecret) {
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(secret, { secret = it.trim() }, singleLine = true, label = { Text("Client secret") },
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp))
        }
        Spacer(Modifier.height(8.dp))
        GradientButton("Save", enabled = id.length > 8 && (!c.needsSecret || secret.length > 10), modifier = Modifier.fillMaxWidth()) {
            onSaveClient(c.provider, id, secret)
        }
        if (c.hasClient) TextButton(onClick = { editing = false }) { Text("Cancel", color = ClaraColors.Muted) }
    } else if (state.connectBusy) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.padding(end = 10.dp).size(18.dp), color = ClaraColors.Cyan, strokeWidth = 2.dp)
            Text("Finish signing in in your browser…", style = MaterialTheme.typography.bodyMedium)
        }
        state.connectLink?.let { link ->
            Text("Browser didn't open? Copy the sign-in link", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan,
                modifier = Modifier.padding(top = 6.dp).clickable {
                    context.getSystemService(android.content.ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Sign-in link", link))
                })
            Text(link, style = MaterialTheme.typography.labelSmall.copy(fontFamily = FontFamily.Monospace), color = ClaraColors.Muted, maxLines = 2)
        }
    } else {
        GradientButton("Connect ${c.name}", modifier = Modifier.fillMaxWidth()) { onConnect(c.provider) }
        Text("You'll sign in and allow access in your browser, then come right back.", style = MaterialTheme.typography.labelSmall,
            color = ClaraColors.Muted, modifier = Modifier.padding(top = 6.dp))
        Row {
            TextButton(onClick = { editing = true }) { Text("Change app ID", color = ClaraColors.Muted) }
            TextButton(onClick = { onDisconnect(c.provider, true) }) { Text("Remove", color = ClaraColors.Muted) }
        }
    }
}
