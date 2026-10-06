package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.ActivityItem
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.data.Job
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ApprovalCard
import info.thewiderlens.clara.ui.components.Mascot
import info.thewiderlens.clara.ui.friendlyTool
import info.thewiderlens.clara.ui.theme.ClaraColors
import java.text.DateFormat
import java.util.Date

@Composable
private fun Header(title: String, subtitle: String, onRefresh: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
        }
        IconButton(onClick = onRefresh) { Icon(Icons.Filled.Refresh, "Refresh", tint = ClaraColors.Muted) }
    }
}

@Composable
private fun Empty(text: String) {
    Column(Modifier.fillMaxWidth().padding(top = 60.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Mascot(size = 90.dp)
        Spacer(Modifier.height(12.dp))
        Text(text, color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium)
    }
}

private fun time(epochSeconds: Double): String =
    DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date((epochSeconds * 1000).toLong()))

// --- Activity: everything Clara did, plus anything waiting on you -------------------
@Composable
fun ActivityScreen(state: UiState, onRefresh: () -> Unit, onAnswer: (Approval, String) -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    Column(Modifier.fillMaxSize()) {
        Header("Updates", "Every step Clara takes, in order", onRefresh)
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp)) {
            if (state.pending.isNotEmpty()) {
                item { Text("Waiting on you", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Magenta, modifier = Modifier.padding(vertical = 6.dp)) }
                items(state.pending, key = { "p-" + it.id }) { a -> ApprovalCard(a) { onAnswer(a, it) } }
                item { Spacer(Modifier.height(12.dp)) }
            }
            val shown = state.activity.filter { it.kind != "tool.completed" }
            if (shown.isEmpty()) item { Empty("Nothing yet. Ask Clara to do something.") }
            items(shown, key = { it.id }) { ActivityRow(it) }
        }
    }
}

@Composable
private fun ActivityRow(a: ActivityItem) {
    val (dot, title) = when {
        a.kind == "tool.started" -> ClaraColors.Cyan to friendlyTool(a.tool).removeSuffix("…")
        a.kind == "approval.requested" -> ClaraColors.Magenta to "Asked for your OK"
        a.kind == "approval.approved" -> ClaraColors.Ok to "You approved"
        a.kind == "approval.denied" -> ClaraColors.Danger to "You denied"
        a.kind == "run.finished" -> ClaraColors.Violet to "Finished"
        a.kind == "job.fired" -> ClaraColors.Magenta to "Scheduled job ran"
        a.kind == "browser.step" -> ClaraColors.Cyan to "In the browser"
        else -> ClaraColors.Muted to a.kind
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(dot))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row {
                Text(title, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Text(time(a.created), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
            }
            a.detail?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

// --- Upcoming: reminders and recurring jobs --------------------------------------
@Composable
fun UpcomingScreen(state: UiState, onRefresh: () -> Unit, onAction: (Job, String) -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    Column(Modifier.fillMaxSize()) {
        Header("Upcoming", "Reminders and things Clara does on a schedule", onRefresh)
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (state.upcoming.isEmpty()) item { Empty("Nothing scheduled. Try “remind me at 6 to call mom”.") }
            items(state.upcoming, key = { it.id }) { j ->
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp))
                        .background(ClaraColors.Panel).padding(16.dp),
                ) {
                    Text((j.name ?: "Job").replace('-', ' ').replaceFirstChar { it.uppercase() }, style = MaterialTheme.typography.titleMedium)
                    Text(j.scheduleText, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
                    j.prompt?.let { Spacer(Modifier.height(6.dp)); Text(it, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(if (j.enabled) "On" else "Paused", color = if (j.enabled) ClaraColors.Ok else ClaraColors.Muted, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
                        TextButton(onClick = { onAction(j, "run") }) { Icon(Icons.Filled.PlayArrow, null, tint = ClaraColors.Cyan); Text(" Run now", color = ClaraColors.Cyan) }
                        TextButton(onClick = { onAction(j, if (j.enabled) "pause" else "resume") }) { Text(if (j.enabled) "Pause" else "Resume", color = ClaraColors.Text) }
                        IconButton(onClick = { onAction(j, "delete") }) { Icon(Icons.Filled.Delete, "Delete", tint = ClaraColors.Danger) }
                    }
                }
            }
        }
    }
}

// --- You: what Clara knows, connection, device ----------------------------------
@Composable
fun YouScreen(state: UiState, onRefresh: () -> Unit, onUnpair: () -> Unit) {
    LaunchedEffect(Unit) { onRefresh() }
    Column(Modifier.fillMaxSize()) {
        Header("You", "What Clara knows, and how she's connected", onRefresh)
        LazyColumn(contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Card("What Clara knows about you", state.memory.user.ifBlank { "Nothing yet. Clara learns as you talk to her." }) }
            item { Card("Clara's notes", state.memory.memory.ifBlank { "No notes yet." }) }
            item { Card("Connection", "${state.bridgeUrl}\n${state.link.name}\n\nEverything stays on your computer. Nothing is sent to a cloud AI.") }
            item {
                OutlinedButton(onClick = onUnpair, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
                    Text("Disconnect this phone", color = ClaraColors.Danger)
                }
            }
        }
    }
}

@Composable
private fun Card(title: String, body: String) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp))
            .background(ClaraColors.Panel).padding(16.dp),
    ) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(8.dp))
        Text(body.trim(), style = MaterialTheme.typography.bodyMedium, color = Color(0xFFD8D6F0))
    }
}
