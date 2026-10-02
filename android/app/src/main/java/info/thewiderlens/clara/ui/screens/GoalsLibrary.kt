package info.thewiderlens.clara.ui.screens

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.Goal
import info.thewiderlens.clara.data.LibraryFile
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.ClaraIcons
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.components.Mood
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors
import java.text.DateFormat
import java.util.Date

private val AREAS = listOf("Health", "Relationships", "Money", "Work", "Home", "Learning", "General")
private val AREA_EMOJI = mapOf("Health" to "💪", "Relationships" to "❤️", "Money" to "💸", "Work" to "💼", "Home" to "🏠", "Learning" to "📚", "General" to "✨")

@Composable
fun TabHeader(title: String, subtitle: String, action: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 14.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
        }
        action()
    }
}

@Composable
private fun EmptyState(text: String, mood: Mood = Mood.Idle) {
    Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        ClaraCharacter(mood, size = 130.dp)
        Spacer(Modifier.height(10.dp))
        Text(text, color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(horizontal = 32.dp))
    }
}

// --- Goals ----------------------------------------------------------------------------
@Composable
fun GoalsScreen(
    state: UiState, onRefresh: () -> Unit, onAdd: (String, String) -> Unit, onToggle: (Goal) -> Unit, onDelete: (Goal) -> Unit, onPlan: (Goal) -> Unit,
    onCheckin: (Goal, String, String, Int) -> Unit = { _, _, _, _ -> }, loadLog: suspend (Goal) -> List<info.thewiderlens.clara.data.GoalLogEntry> = { emptyList() },
    onCheckinNow: (Goal) -> Unit = {},
) {
    LaunchedEffect(Unit) { onRefresh() }
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Goal?>(null) }
    Column(Modifier.fillMaxSize()) {
        TabHeader("Goals", "What you're working toward — Clara helps you get there") {
            IconButton(onClick = { adding = true }) { Icon(Icons.Filled.Add, "Add goal", tint = ClaraColors.Cyan) }
        }
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
            if (state.goals.isEmpty()) item { EmptyState("No goals yet. Tap + to add one, like “sleep 8 hours” or “save $500 this month”.") }
            val byArea = state.goals.groupBy { it.area }
            for (area in AREAS + (byArea.keys - AREAS.toSet())) {
                val goals = byArea[area] ?: continue
                item(key = "h-$area") {
                    Text("${AREA_EMOJI[area] ?: "✨"}  $area", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))
                }
                items(goals, key = { it.id }) { g -> GoalRow(g, onToggle, onDelete, onPlan) { editing = g } }
            }
        }
    }
    if (adding) AddGoalDialog(onDismiss = { adding = false }, onAdd = { t, a -> onAdd(t, a); adding = false })
    editing?.let { g -> CheckinSheet(g, loadLog, onSave = { c, t, d -> onCheckin(g, c, t, d); editing = null }, onNow = { onCheckinNow(g); editing = null }, onDismiss = { editing = null }) }
}

private val DAYS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

fun prettyTime(hhmm: String?): String {
    val (h, m) = (hhmm ?: "19:00").split(":").map { it.toIntOrNull() ?: 0 }.let { it[0] to it.getOrElse(1) { 0 } }
    return "%d:%02d %s".format(if (h % 12 == 0) 12 else h % 12, m, if (h < 12) "AM" else "PM")
}

private fun checkinLabel(g: Goal): String? = when (g.checkin) {
    "daily" -> "Daily · ${prettyTime(g.checkinTime)}"
    "weekly" -> "${DAYS[(g.checkinDay ?: 6).coerceIn(0, 6)]}s · ${prettyTime(g.checkinTime)}"
    else -> null
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun CheckinSheet(
    g: Goal, loadLog: suspend (Goal) -> List<info.thewiderlens.clara.data.GoalLogEntry>,
    onSave: (String, String, Int) -> Unit, onNow: () -> Unit, onDismiss: () -> Unit,
) {
    var mode by remember { mutableStateOf(g.checkin ?: "off") }
    var day by remember { mutableStateOf(g.checkinDay ?: 6) }
    val (h0, m0) = (g.checkinTime ?: "19:00").split(":").map { it.toIntOrNull() ?: 0 }.let { it[0] to it.getOrElse(1) { 0 } }
    val clock = androidx.compose.material3.rememberTimePickerState(h0, m0, is24Hour = false)
    var pickTime by remember { mutableStateOf(false) }
    var log by remember { mutableStateOf<List<info.thewiderlens.clara.data.GoalLogEntry>?>(null) }
    LaunchedEffect(g.id) { log = loadLog(g) }
    val hhmm = "%02d:%02d".format(clock.hour, clock.minute)

    androidx.compose.material3.ModalBottomSheet(onDismissRequest = onDismiss, containerColor = ClaraColors.Panel) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp).verticalScroll(rememberScrollState())) {
            Text(g.title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text("Clara checks in with you about this goal and keeps track of how it's going.", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
            Spacer(Modifier.height(16.dp))
            Text("Check-ins", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("off" to "Off", "daily" to "Daily", "weekly" to "Weekly").forEach { (k, label) -> Pill(label, mode == k) { mode = k } }
            }
            if (mode == "weekly") {
                Spacer(Modifier.height(10.dp))
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    DAYS.forEachIndexed { i, d -> Pill(d, day == i) { day = i } }
                }
            }
            if (mode != "off") {
                Spacer(Modifier.height(10.dp))
                Pill("🔔  at ${prettyTime(hhmm)}", false) { pickTime = true }
            }
            Spacer(Modifier.height(18.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                GradientButton("Save", onClick = { onSave(mode, hhmm, day) }, modifier = Modifier.weight(1f))
                androidx.compose.material3.OutlinedButton(onClick = onNow, modifier = Modifier.weight(1f), shape = RoundedCornerShape(14.dp)) {
                    Text("Check in now", color = ClaraColors.Cyan)
                }
            }
            Spacer(Modifier.height(20.dp))
            Text("History", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
            Spacer(Modifier.height(6.dp))
            val entries = log
            when {
                entries == null -> Text("Loading…", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
                entries.isEmpty() -> Text("Nothing yet. Your check-ins and answers show up here.", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
                else -> entries.take(15).forEach { e ->
                    val whenText = java.text.SimpleDateFormat("EEE MMM d", androidx.compose.ui.platform.LocalConfiguration.current.locales[0]).format(java.util.Date((e.created * 1000).toLong()))
                    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                        Text(if (e.kind == "checkin") "Clara" else "You", style = MaterialTheme.typography.labelMedium,
                            color = if (e.kind == "checkin") ClaraColors.Violet else ClaraColors.Cyan, modifier = Modifier.width(48.dp))
                        Column(Modifier.weight(1f)) {
                            Text(e.text, style = MaterialTheme.typography.bodyMedium, maxLines = 4, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                            Text(whenText, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                        }
                    }
                }
            }
        }
    }
    if (pickTime) {
        AlertDialog(
            onDismissRequest = { pickTime = false }, containerColor = ClaraColors.Panel,
            confirmButton = { TextButton(onClick = { pickTime = false }) { Text("Done", color = ClaraColors.Cyan) } },
            text = { androidx.compose.material3.TimePicker(clock) },
        )
    }
}

@Composable
private fun Pill(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label, style = MaterialTheme.typography.bodyMedium,
        color = if (selected) Color.White else ClaraColors.Text,
        modifier = Modifier.clip(RoundedCornerShape(16.dp))
            .then(if (selected) Modifier.background(ClaraBrush.bubble) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)))
            .clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp),
    )
}

@Composable
private fun GoalRow(g: Goal, onToggle: (Goal) -> Unit, onDelete: (Goal) -> Unit, onPlan: (Goal) -> Unit, onOpen: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel)
            .border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(26.dp).clip(CircleShape)
                .then(if (g.done) Modifier.background(ClaraBrush.bubble) else Modifier.border(2.dp, ClaraColors.Muted, CircleShape))
                .clickable { onToggle(g) },
            contentAlignment = Alignment.Center,
        ) { if (g.done) Icon(Icons.Filled.Check, null, tint = Color.White, modifier = Modifier.size(16.dp)) }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).clickable(onClick = onOpen)) {
            Text(
                g.title, style = MaterialTheme.typography.bodyLarge,
                color = if (g.done) ClaraColors.Muted else ClaraColors.Text,
                textDecoration = if (g.done) TextDecoration.LineThrough else null,
            )
            if (!g.done) Text(checkinLabel(g)?.let { "🔔 $it" } ?: "Set up check-ins", style = MaterialTheme.typography.labelSmall,
                color = if (checkinLabel(g) != null) ClaraColors.Cyan else ClaraColors.Muted)
        }
        if (!g.done) TextButton(onClick = { onPlan(g) }) { Text("Plan", color = ClaraColors.Cyan) }
        IconButton(onClick = { onDelete(g) }) { Icon(Icons.Filled.Close, "Remove", tint = ClaraColors.Muted, modifier = Modifier.size(18.dp)) }
    }
}

@Composable
private fun AddGoalDialog(onDismiss: () -> Unit, onAdd: (String, String) -> Unit) {
    var title by remember { mutableStateOf("") }
    var area by remember { mutableStateOf("Health") }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = ClaraColors.Panel,
        title = { Text("New goal") },
        text = {
            Column {
                OutlinedTextField(title, { title = it }, placeholder = { Text("e.g. Walk 8,000 steps a day") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp))
                Spacer(Modifier.height(12.dp))
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    AREAS.forEach { a ->
                        Text(
                            "${AREA_EMOJI[a]} $a", style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.clip(RoundedCornerShape(12.dp))
                                .then(if (a == area) Modifier.background(ClaraBrush.bubble) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(12.dp)))
                                .clickable { area = a }.padding(horizontal = 10.dp, vertical = 7.dp),
                        )
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = { if (title.isNotBlank()) onAdd(title.trim(), area) }) { Text("Add", color = ClaraColors.Cyan) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", color = ClaraColors.Muted) } },
    )
}

// --- Library ----------------------------------------------------------------------------
@Composable
fun LibraryScreen(state: UiState, onRefresh: () -> Unit, load: suspend (String) -> ByteArray?) {
    LaunchedEffect(Unit) { onRefresh() }
    var open by remember { mutableStateOf<LibraryFile?>(null) }
    Column(Modifier.fillMaxSize()) {
        TabHeader("Library", "Everything Clara has made for you") {
            IconButton(onClick = onRefresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = ClaraColors.Muted) }
        }
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (state.library.isEmpty()) item { EmptyState("Nothing here yet. Reports, images, and files Clara creates will show up here.") }
            items(state.library, key = { it.path }) { f ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp))
                        .clickable { open = f }.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).background(ClaraColors.Raised), contentAlignment = Alignment.Center) {
                        Text(when (f.kind) { "image" -> "🖼️"; "text" -> "📝"; "pdf" -> "📄"; else -> "📦" })
                    }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(f.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date((f.modified * 1000).toLong())) + " · " + humanSize(f.size),
                            style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                        )
                    }
                }
            }
        }
    }
    open?.let { f -> FileViewer(f, load) { open = null } }
}

private fun humanSize(b: Long) = when {
    b < 1024 -> "$b B"
    b < 1024 * 1024 -> "${b / 1024} KB"
    else -> "%.1f MB".format(b / 1048576.0)
}

@Composable
private fun FileViewer(f: LibraryFile, load: suspend (String) -> ByteArray?, onClose: () -> Unit) {
    var text by remember { mutableStateOf<String?>(null) }
    var image by remember { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(f.path) {
        if (f.kind == "video") return@LaunchedEffect   // played by the video player below
        val bytes = load(f.path)
        when (f.kind) {
            "image" -> image = bytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
            "text" -> text = bytes?.decodeToString()?.take(100_000) ?: "Couldn't open this file."
            else -> text = "This file is on your computer at:\n~/clara/workspace/${f.path}"
        }
    }
    if (f.kind == "video") { info.thewiderlens.clara.ui.components.VideoPlayerDialog(f.path, load, onClose); return }
    AlertDialog(
        onDismissRequest = onClose, containerColor = ClaraColors.Panel,
        title = { Text(f.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Box(Modifier.heightIn(max = 520.dp)) {
                image?.let { Image(it, f.name, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth()) }
                text?.let {
                    Text(
                        it, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = if (f.name.endsWith(".md")) FontFamily.Default else FontFamily.Monospace),
                        modifier = Modifier.verticalScroll(rememberScrollState()),
                    )
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text("Close", color = ClaraColors.Cyan) } },
    )
}
