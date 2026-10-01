package info.thewiderlens.clara.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.SpendSummary
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.theme.ClaraColors
import java.text.SimpleDateFormat
import java.util.Locale

private val KIND_COLORS = mapOf(
    "agent" to Color(0xFF5B3CF5), "image" to Color(0xFF58DBFB), "video" to Color(0xFFD53CD1), "music" to Color(0xFFFFD23F),
)
private val KIND_EMOJI = mapOf("agent" to "🧠", "image" to "🎨", "video" to "🎬", "music" to "🎵")

private fun money(v: Double?, digits: Int = 2) = if (v == null) "—" else "$" + "%.${digits}f".format(v)

/** Where cloud money goes: totals, a 30-day chart, what it was spent on, caps and the OpenRouter balance. */
@Composable
fun SpendingPage(
    state: UiState, onRefresh: () -> Unit,
    onCaps: (daily: Double?, clearDaily: Boolean, monthly: Double?, clearMonthly: Boolean) -> Unit, onBack: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    val s = state.spend
    var editing by remember { mutableStateOf<String?>(null) }   // "daily" | "monthly"
    PageScaffold("Spending", onBack) {
        if (s == null) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Loading…", color = ClaraColors.Muted) }
            return@PageScaffold
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Only cloud boost costs money: coding helpers, pictures, videos and music. Everything else Clara does runs free on your computer.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Stat("Today", money(s.today), Modifier.weight(1f))
                Stat("7 days", money(s.week), Modifier.weight(1f))
                Stat("This month", money(s.month), Modifier.weight(1f), sub = "on pace for " + money(s.projectedMonth))
            }

            Card("Budget") {
                CapBar("Today", s.today, s.dailyCap) { editing = "daily" }
                Spacer(Modifier.height(10.dp))
                CapBar("This month", s.month, s.monthlyCap) { editing = "monthly" }
                Spacer(Modifier.height(6.dp))
                Text("Only you can set these. Clara stops using the cloud when one is reached and tells you at 80%.",
                    style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
            }

            s.openrouter?.let { b -> BalanceCard(b.balance, b.keyRemaining, b.keyLimit) }

            Card("Last 30 days") { SpendChart(s) }

            if (s.byKind.isNotEmpty()) Card("Where it went this month") {
                val max = s.byKind.maxOf { it.cost }.coerceAtLeast(0.0001)
                s.byKind.forEach { k ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(KIND_EMOJI[k.kind] ?: "☁️")
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Row { Text(k.name, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f)); Text(money(k.cost), style = MaterialTheme.typography.bodyMedium) }
                            Spacer(Modifier.height(4.dp))
                            Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(ClaraColors.Raised)) {
                                Box(Modifier.fillMaxWidth((k.cost / max).toFloat()).height(6.dp).clip(RoundedCornerShape(3.dp)).background(KIND_COLORS[k.kind] ?: ClaraColors.Cyan))
                            }
                            Text("${k.count} ${if (k.count == 1) "use" else "uses"}", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                        }
                    }
                }
            }

            if (s.topTasks.isNotEmpty()) Card("Biggest costs this month") {
                s.topTasks.forEach { t ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(KIND_EMOJI[t.kind] ?: "☁️")
                        Spacer(Modifier.width(8.dp))
                        Column(Modifier.weight(1f)) {
                            Text(t.label.substringAfter(" · "), style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            val whenText = if (t.last > 0) SimpleDateFormat("MMM d", Locale.getDefault()).format(java.util.Date((t.last * 1000).toLong())) else ""
                            Text(listOfNotNull(whenText, t.chat?.let { "in “${it.take(30)}”" }, if (t.calls > 1) "${t.calls} calls" else null).joinToString(" · "),
                                style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                        }
                        Text(money(t.cost), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            if (s.byModel.isNotEmpty()) Card("Models") {
                s.byModel.forEach { m ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                        Text(m.model, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(money(m.cost, if (m.cost < 0.1) 3 else 2), style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)
                    }
                }
            }
            Text("All time: " + money(s.allTime), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
            Spacer(Modifier.height(16.dp))
        }
    }
    editing?.let { which ->
        CapDialog(if (which == "daily") "Daily cap" else "Monthly cap", if (which == "daily") s?.dailyCap else s?.monthlyCap,
            onSet = { v -> if (which == "daily") onCaps(v, false, null, false) else onCaps(null, false, v, false); editing = null },
            onClear = { if (which == "daily") onCaps(null, true, null, false) else onCaps(null, false, null, true); editing = null },
            onDismiss = { editing = null })
    }
}

@Composable
private fun Card(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier, sub: String? = null) {
    Column(modifier.clip(RoundedCornerShape(16.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(16.dp)).padding(12.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
        Text(value, style = MaterialTheme.typography.titleLarge)
        sub?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted, maxLines = 1) }
    }
}

@Composable
private fun CapBar(label: String, spent: Double, cap: Double?, onEdit: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text(if (cap == null) money(spent) + " · no cap" else money(spent) + " of " + money(cap), style = MaterialTheme.typography.bodyMedium)
        TextButton(onClick = onEdit) { Text(if (cap == null) "Set cap" else "Change", color = ClaraColors.Cyan) }
    }
    if (cap != null && cap > 0) {
        val frac = (spent / cap).coerceIn(0.0, 1.0).toFloat()
        val color = when { frac >= 1f -> ClaraColors.Magenta; frac >= 0.8f -> Color(0xFFFFB020); else -> ClaraColors.Cyan }
        Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(ClaraColors.Raised)) {
            Box(Modifier.fillMaxWidth(frac).height(8.dp).clip(RoundedCornerShape(4.dp)).background(color))
        }
    }
}

@Composable
private fun BalanceCard(balance: Double?, keyRemaining: Double?, keyLimit: Double?) {
    val context = LocalContext.current
    val low = balance != null && balance < 3
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
            .border(if (low) 1.5.dp else 1.dp, if (low) Color(0xFFFFB020) else ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp),
    ) {
        Text("OpenRouter credit", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(4.dp))
        Text(money(balance) + " left", style = MaterialTheme.typography.headlineSmall, color = if (low) Color(0xFFFFB020) else ClaraColors.Text)
        Text("Your whole OpenRouter account (other apps too)." + (if (keyLimit != null) " Clara's key: ${money(keyRemaining)} of ${money(keyLimit)} limit left." else ""),
            style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
        if (low) Text("Running low: cloud coding, pictures and videos stop when it hits zero.", style = MaterialTheme.typography.labelMedium, color = Color(0xFFFFB020))
        TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://openrouter.ai/settings/credits"))) }) {
            Text("Add credit on openrouter.ai", color = ClaraColors.Cyan)
        }
    }
}

@Composable
private fun SpendChart(s: SpendSummary) {
    var picked by remember(s) { mutableStateOf(s.daily.indexOfLast { it.total > 0 }.takeIf { it >= 0 } ?: (s.daily.size - 1)) }
    val maxDay = (s.daily.maxOfOrNull { it.total } ?: 0.0).coerceAtLeast(0.01)
    val order = listOf("agent", "image", "music", "video")
    Canvas(
        Modifier.fillMaxWidth().height(140.dp).pointerInput(s) {
            detectTapGestures { pos -> picked = ((pos.x / size.width) * s.daily.size).toInt().coerceIn(0, s.daily.size - 1) }
        },
    ) {
        val n = s.daily.size.coerceAtLeast(1)
        val slot = size.width / n
        val barW = slot * 0.7f
        drawLine(ClaraColors.Line, Offset(0f, size.height), Offset(size.width, size.height), strokeWidth = 2f)
        s.daily.forEachIndexed { i, d ->
            var top = size.height
            val x = i * slot + (slot - barW) / 2
            if (i == picked) drawRoundRect(Color.White.copy(alpha = 0.08f), Offset(i * slot, 0f), Size(slot, size.height), CornerRadius(6f, 6f))
            order.forEach { k ->
                val v = d.kinds[k] ?: 0.0
                if (v > 0) {
                    val h = (v / maxDay * (size.height - 8)).toFloat().coerceAtLeast(3f)
                    drawRoundRect(KIND_COLORS[k] ?: Color.Gray, Offset(x, top - h), Size(barW, h), CornerRadius(3f, 3f))
                    top -= h
                }
            }
        }
    }
    val d = s.daily.getOrNull(picked)
    if (d != null) {
        val day = runCatching { SimpleDateFormat("EEE MMM d", Locale.getDefault()).format(SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(d.date)!!) }.getOrDefault(d.date)
        Spacer(Modifier.height(8.dp))
        Text("$day · ${money(d.total)}", style = MaterialTheme.typography.bodyMedium)
        if (d.kinds.isNotEmpty()) Text(d.kinds.entries.sortedByDescending { it.value }.joinToString("  ") { (KIND_EMOJI[it.key] ?: "") + " " + money(it.value) },
            style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
    }
    Spacer(Modifier.height(6.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        listOf("agent" to "Helpers", "image" to "Pictures", "video" to "Videos", "music" to "Music").forEach { (k, name) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(KIND_COLORS[k]!!))
                Spacer(Modifier.width(4.dp))
                Text(name, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
            }
        }
    }
}

@Composable
private fun CapDialog(title: String, current: Double?, onSet: (Double) -> Unit, onClear: () -> Unit, onDismiss: () -> Unit) {
    var text by remember { mutableStateOf(current?.let { "%.2f".format(it) } ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss, containerColor = ClaraColors.Panel,
        title = { Text(title) },
        text = {
            OutlinedTextField(text, { text = it.filter { c -> c.isDigit() || c == '.' } }, singleLine = true, label = { Text("Dollars") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
        },
        confirmButton = { TextButton(enabled = text.toDoubleOrNull() != null, onClick = { text.toDoubleOrNull()?.let(onSet) }) { Text("Set", color = ClaraColors.Cyan) } },
        dismissButton = { TextButton(onClick = onClear) { Text("No cap", color = ClaraColors.Muted) } },
    )
}
