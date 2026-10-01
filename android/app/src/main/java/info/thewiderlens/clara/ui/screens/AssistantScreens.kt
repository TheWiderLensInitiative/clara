package info.thewiderlens.clara.ui.screens

import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.ShoppingCart
import kotlinx.coroutines.launch
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.Link
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.data.Job
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.ClaraIcons
import info.thewiderlens.clara.ui.moodOf
import info.thewiderlens.clara.ui.theme.ClaraColors
import kotlinx.coroutines.delay

@Composable
fun PageScaffold(title: String, onBack: () -> Unit, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize().background(ClaraColors.Black)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = ClaraColors.Text) }
            Text(title, style = MaterialTheme.typography.titleMedium)
        }
        Box(Modifier.weight(1f)) { content() }
    }
}

/** The assistant menu: the agent itself, and everything about how it runs. */
@Composable
fun AssistantHub(state: UiState, onOpen: (String) -> Unit, onBack: () -> Unit) {
    PageScaffold("Clara", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                ClaraCharacter(moodOf(state), size = 150.dp)
                Text("Clara", style = MaterialTheme.typography.headlineMedium)
                Text(
                    if (state.link == Link.Online) "Running privately on your computer" else "Can't reach your computer right now",
                    style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted,
                )
            }
            Spacer(Modifier.height(20.dp))
            HubRow(Icons.Filled.DateRange, "Upcoming", "Reminders and scheduled jobs", badge = state.upcoming.size.takeIf { it > 0 }?.toString()) { onOpen("upcoming") }
            HubRow(ClaraIcons.Monitor, "Screen", "Watch Clara's browser live") { onOpen("screen") }
            HubRow(Icons.AutoMirrored.Filled.List, "Updates", "Every step Clara takes", badge = state.pending.size.takeIf { it > 0 }?.let { "$it waiting" }) { onOpen("updates") }
            HubRow(Icons.Filled.Face, "Identity", "Clara's personality and what she remembers") { onOpen("identity") }
            HubRow(Icons.Filled.Star, "Clara's look", "Colors, style and accessories · she can restyle herself") { onOpen("look") }
            HubRow(Icons.Filled.Lock, "Passwords", "Logins Clara can use without seeing them") { onOpen("passwords") }
            HubRow(Icons.Filled.Email, "Connectors", "Gmail, Outlook, Spotify, Notion, Slack, YouTube and more",
                badge = state.connectors.count { it.connected }.takeIf { it > 0 }?.let { "$it connected" }) { onOpen("connectors") }
            HubRow(Icons.Filled.Build, "API keys", "Services Clara can call without seeing the key") { onOpen("apikeys") }
            HubRow(Icons.Filled.Star, "Cloud AI", "Stronger models for coding and images · budget", badge = if (state.cloud.spentToday > 0) "$" + "%.2f".format(state.cloud.spentToday) + " today" else null) { onOpen("cloud") }
            HubRow(ClaraIcons.Chart, "Spending", "What cloud boost costs, day by day · caps · credit",
                badge = if (state.cloud.spentMonth > 0) "$" + "%.2f".format(state.cloud.spentMonth) + " this month" else null) { onOpen("spending") }
            HubRow(Icons.Filled.ShoppingCart, "Brand kit", "Your logo, colors and call to action for ads") { onOpen("brand") }
            HubRow(Icons.Filled.Settings, "Settings", "Connection, this phone, privacy") { onOpen("settings") }
        }
    }
}

@Composable
private fun HubRow(icon: ImageVector, title: String, subtitle: String, badge: String? = null, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 5.dp).clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
            .border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).clickable(onClick = onClick).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = ClaraColors.Cyan, modifier = Modifier.size(24.dp))
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
        }
        badge?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Magenta, modifier = Modifier.padding(end = 6.dp)) }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = ClaraColors.Muted)
    }
}

@Composable
fun UpcomingPage(state: UiState, onRefresh: () -> Unit, onAction: (Job, String) -> Unit, onBack: () -> Unit) =
    PageScaffold("", onBack) { UpcomingScreen(state, onRefresh, onAction) }

@Composable
fun UpdatesPage(state: UiState, onRefresh: () -> Unit, onAnswer: (Approval, String) -> Unit, onBack: () -> Unit) =
    PageScaffold("", onBack) { ActivityScreen(state, onRefresh, onAnswer) }

/** The Screen page: check on the agent's computer without interrupting it. */
@Composable
fun ScreenPage(state: UiState, onRefresh: () -> Unit, onBack: () -> Unit) {
    LaunchedEffect(Unit) { while (true) { onRefresh(); delay(2500) } }
    PageScaffold("Screen", onBack) {
        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(if (state.working) ClaraColors.Ok else ClaraColors.Muted))
                Spacer(Modifier.width(8.dp))
                Text(
                    if (state.working) "Live · ${state.status.ifBlank { "Clara is working" }}" else "Clara's browser · last thing she looked at",
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                )
            }
            Spacer(Modifier.height(10.dp))
            val shot = state.screenshot
            if (shot == null) {
                Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    ClaraCharacter(moodOf(state), size = 130.dp)
                    Text("Nothing on screen yet. When Clara uses her browser, you'll see it here.", color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium)
                }
            } else {
                Image(
                    shot, "Clara's screen", contentScale = ContentScale.FillWidth,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)),
                )
            }
        }
    }
}

/** Identity: the files that make up the agent, editable by you. */
@Composable
fun IdentityPage(state: UiState, onRefresh: () -> Unit, onSave: (String, String) -> Unit, onBack: () -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    var editing by remember { mutableStateOf<Pair<String, String>?>(null) }
    PageScaffold("Identity", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            IdentityCard("Soul", "Clara's personality and how she talks", state.identity.soul) { editing = "soul" to state.identity.soul }
            IdentityCard("About you", "What Clara has learned about you", state.identity.user) { editing = "user" to state.identity.user }
            IdentityCard("Clara's notes", "Things she keeps track of", state.identity.memory) { editing = "memory" to state.identity.memory }
            Spacer(Modifier.height(20.dp))
        }
    }
    editing?.let { (name, current) ->
        var text by remember(name) { mutableStateOf(current) }
        AlertDialog(
            onDismissRequest = { editing = null }, containerColor = ClaraColors.Panel,
            title = { Text("Edit") },
            text = { OutlinedTextField(text, { text = it }, modifier = Modifier.fillMaxWidth().heightIn(min = 200.dp, max = 420.dp)) },
            confirmButton = { TextButton(onClick = { onSave(name, text); editing = null }) { Text("Save", color = ClaraColors.Cyan) } },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("Cancel", color = ClaraColors.Muted) } },
        )
    }
}

@Composable
private fun IdentityCard(title: String, subtitle: String, body: String, onEdit: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(subtitle, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
            }
            TextButton(onClick = onEdit) { Text("Edit", color = ClaraColors.Cyan) }
        }
        Spacer(Modifier.height(6.dp))
        Text(body.ifBlank { "Nothing yet." }.trim(), style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Text.copy(alpha = 0.85f), maxLines = 12, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun SettingsPage(
    state: UiState, onUnpair: () -> Unit, onBack: () -> Unit,
    onVoiceRefresh: () -> Unit = {}, onPickVoice: (String) -> Unit = {}, speech: suspend (String) -> ByteArray? = { null },
    onProactiveRefresh: () -> Unit = {}, onProactive: (info.thewiderlens.clara.data.ProactiveSettings) -> Unit = {}, onSendNow: () -> Unit = {},
) {
    androidx.compose.runtime.LaunchedEffect(Unit) { onVoiceRefresh(); onProactiveRefresh() }
    PageScaffold("Settings", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SettingCard("Connection", "${state.bridgeUrl}\n" + when {
                state.link != Link.Online -> state.link.name
                state.via == "remote" -> "Connected from away, through Tailscale"
                else -> "Connected on your home Wi-Fi"
            })
            SettingCard("Remote access", state.remoteUrl?.let {
                "Ready: $it\nWhen you're away from home, Clara connects through Tailscale by herself. Keep the Tailscale app on this phone signed in."
            } ?: ("Not set up yet. On the PC run:  sudo sh ~/clara/setup/tailscale.sh\nthen install the Tailscale app on this phone and sign in with the same account. " +
                  "Clara picks it up automatically, no re-pairing."))
            ProactiveCard(state.proactive, onProactive, onSendNow)
            VoicePicker(state, onPickVoice, speech)
            SettingCard("Privacy", "Clara runs on your computer: the model, the agent, search, memory, and her voice. " +
                "Only when you allow cloud boost for a task (coding, pictures) is that task sent to the cloud model you chose. Nothing is used for training.")
            SettingCard("Permissions", "Reading, browsing, and research run freely. Sending, deleting, buying, installing, and admin commands always ask you first. Clara can never change her own safety rules.")
            OutlinedButton(onClick = onUnpair, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
                Text("Disconnect this phone", color = ClaraColors.Danger)
            }
        }
    }
}

@Composable
private fun SettingCard(title: String, body: String) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(6.dp))
        Text(body, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun VoicePicker(state: UiState, onPick: (String) -> Unit, speech: suspend (String) -> ByteArray?) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    var playing by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text("Clara's voice", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(4.dp))
        Text("Used in voice mode. Made on your computer, never in the cloud. Tap a name to choose it.", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
        Spacer(Modifier.height(8.dp))
        if (state.voice.voices.isEmpty()) Text("Loading voices…", style = MaterialTheme.typography.bodyMedium)
        state.voice.voices.forEach { v ->
            val chosen = v.id == state.voice.voice
            androidx.compose.foundation.layout.Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(if (chosen) ClaraColors.Raised else androidx.compose.ui.graphics.Color.Transparent)
                    .clickable {
                        onPick(v.id)
                        playing = v.id
                        scope.launch {
                            kotlinx.coroutines.delay(400)  // let the choice save, then let them hear it
                            speech("Hi, I'm Clara. This is how I'll sound.")?.let { playPreview(context, it) }
                            playing = null
                        }
                    }
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(v.name, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                if (playing == v.id) Text("playing…", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                else if (chosen) Text("✓", color = ClaraColors.Cyan)
            }
        }
    }
}

private suspend fun playPreview(context: android.content.Context, wav: ByteArray) {
    val f = java.io.File(context.cacheDir, "voice-preview.wav").apply { writeBytes(wav) }
    kotlinx.coroutines.suspendCancellableCoroutine { cont ->
        val mp = android.media.MediaPlayer()
        runCatching {
            mp.setDataSource(f.absolutePath)
            mp.setOnCompletionListener { it.release(); if (cont.isActive) cont.resumeWith(Result.success(Unit)) }
            mp.prepare(); mp.start()
        }.onFailure { mp.release(); if (cont.isActive) cont.resumeWith(Result.success(Unit)) }
        cont.invokeOnCancellation { runCatching { mp.stop(); mp.release() } }
    }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun ProactiveCard(p: info.thewiderlens.clara.data.ProactiveSettings, onChange: (info.thewiderlens.clara.data.ProactiveSettings) -> Unit, onSendNow: () -> Unit) {
    var picking by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<String?>(null) }  // which time is being edited
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text("Clara reaches out", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(4.dp))
        Text("A morning note with a few things she can do for you, plus the goal check-ins you set in Goals.", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
        Spacer(Modifier.height(10.dp))
        androidx.compose.foundation.layout.Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Morning note", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            androidx.compose.material3.Switch(p.daily, { onChange(p.copy(daily = it)) },
                colors = androidx.compose.material3.SwitchDefaults.colors(checkedTrackColor = ClaraColors.Violet))
        }
        if (p.daily) TimeRow("Sends at", p.time) { picking = "time" }
        TimeRow("Quiet from", p.quietStart) { picking = "quietStart" }
        TimeRow("Quiet until", p.quietEnd) { picking = "quietEnd" }
        Spacer(Modifier.height(10.dp))
        OutlinedButton(onClick = onSendNow, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
            Text("Send me one now", color = ClaraColors.Cyan)
        }
    }
    picking?.let { which ->
        val current = when (which) { "time" -> p.time; "quietStart" -> p.quietStart; else -> p.quietEnd }
        val (h, m) = current.split(":").map { it.toIntOrNull() ?: 0 }.let { it[0] to it.getOrElse(1) { 0 } }
        val clock = androidx.compose.material3.rememberTimePickerState(h, m, is24Hour = false)
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { picking = null }, containerColor = ClaraColors.Panel,
            confirmButton = {
                androidx.compose.material3.TextButton(onClick = {
                    val t = "%02d:%02d".format(clock.hour, clock.minute)
                    onChange(when (which) { "time" -> p.copy(time = t); "quietStart" -> p.copy(quietStart = t); else -> p.copy(quietEnd = t) })
                    picking = null
                }) { Text("Done", color = ClaraColors.Cyan) }
            },
            text = { androidx.compose.material3.TimePicker(clock) },
        )
    }
}

@Composable
private fun TimeRow(label: String, hhmm: String, onClick: () -> Unit) {
    androidx.compose.foundation.layout.Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, modifier = Modifier.weight(1f))
        Text(info.thewiderlens.clara.ui.screens.prettyTime(hhmm), style = MaterialTheme.typography.bodyLarge, color = ClaraColors.Cyan)
    }
}
