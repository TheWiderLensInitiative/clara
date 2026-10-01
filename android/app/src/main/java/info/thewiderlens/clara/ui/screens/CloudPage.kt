package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
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
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.BudgetCard
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors
import java.text.DateFormat
import java.util.Date

private val AGENT_MODELS = listOf("anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5", "openai/gpt-5.5", "google/gemini-3.1-pro-preview")
private val IMAGE_MODELS = listOf("google/gemini-3.1-flash-image", "openai/gpt-image-2", "black-forest-labs/flux.2-pro", "recraft/recraft-v4.1-vector")

@Composable
private fun Card(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun ModelPicker(current: String, presets: List<String>, onPick: (String) -> Unit) {
    var custom by remember(current) { mutableStateOf(current) }
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        presets.forEach { m ->
            Text(m.substringAfter('/'), style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.clip(RoundedCornerShape(12.dp))
                    .then(if (m == current) Modifier.background(ClaraBrush.bubble) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(12.dp)))
                    .clickable { onPick(m) }.padding(horizontal = 10.dp, vertical = 7.dp))
        }
    }
    Spacer(Modifier.height(6.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(custom, { custom = it.trim() }, singleLine = true, label = { Text("Any OpenRouter model id") }, modifier = Modifier.weight(1f))
        TextButton(enabled = custom.contains('/') && custom != current, onClick = { onPick(custom) }) { Text("Use", color = ClaraColors.Cyan) }
    }
}

/** Cloud boost: which cloud models Clara may call in, what they cost today, and the cap only you can set. */
@Composable
fun CloudPage(
    state: UiState, onRefresh: () -> Unit, onKey: (String) -> Unit,
    onUpdate: (agent: String?, image: String?, cap: Double?, clearCap: Boolean, always: Boolean?) -> Unit,
    onBudget: (info.thewiderlens.clara.data.BudgetSuggestion, Boolean) -> Unit, onBack: () -> Unit,
    onVideoRefresh: () -> Unit = {}, onVideoModel: (String) -> Unit = {}, onSpending: () -> Unit = {},
) {
    LaunchedEffect(Unit) { onRefresh(); onVideoRefresh() }
    val c = state.cloud
    var key by remember { mutableStateOf("") }
    var cap by remember(c.cap) { mutableStateOf(c.cap?.let { "%.2f".format(it) } ?: "") }
    PageScaffold("Cloud AI", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Clara thinks locally on your computer. For serious coding and images she can call in a cloud model through your " +
                "OpenRouter account — only after you say so, and only within the budget you set.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
            state.budgetSuggestions.forEach { b -> BudgetCard(b) { onBudget(b, it) } }
            Card("OpenRouter key") {
                if (c.hasKey) Text("Saved  ••••••••  (Clara never sees it)", style = MaterialTheme.typography.bodyLarge)
                else {
                    Text("Not set. Paste your OpenRouter API key (openrouter.ai → Keys).", style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
                    Spacer(Modifier.height(6.dp))
                    OutlinedTextField(key, { key = it }, singleLine = true, label = { Text("sk-or-…") }, visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
                    Spacer(Modifier.height(8.dp))
                    GradientButton("Save key", enabled = key.length > 10, modifier = Modifier.fillMaxWidth()) { onKey(key); key = "" }
                }
            }
            Card("Today") {
                Text("$" + "%.2f".format(c.spentToday) + (c.cap?.let { " of $" + "%.2f".format(it) + " daily cap" } ?: " spent · no daily cap"),
                    style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(cap, { cap = it.filter { ch -> ch.isDigit() || ch == '.' } }, singleLine = true, label = { Text("Daily cap ($)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
                    TextButton(onClick = { cap.toDoubleOrNull()?.let { onUpdate(null, null, it, false, null) } }) { Text("Set", color = ClaraColors.Cyan) }
                    TextButton(onClick = { onUpdate(null, null, null, true, null) }) { Text("No cap", color = ClaraColors.Muted) }
                }
                Text("Only you can change this. Clara can suggest a cap; you'll see it here to accept or decline.",
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                TextButton(onClick = onSpending) { Text("Spending dashboard, monthly cap and credit →", color = ClaraColors.Cyan) }
            }
            Card("Ask before using the cloud") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (c.always) "Off — Clara may use the cloud whenever she needs it (still within your cap)"
                         else "On — Clara asks once per task", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    Switch(checked = !c.always, onCheckedChange = { onUpdate(null, null, null, false, !it) },
                        colors = SwitchDefaults.colors(checkedTrackColor = ClaraColors.Violet))
                }
            }
            Card("Model for coding and hard tasks") { ModelPicker(c.agentModel, AGENT_MODELS) { onUpdate(it, null, null, false, null) } }
            Card("Model for images") { ModelPicker(c.imageModel, IMAGE_MODELS) { onUpdate(null, it, null, false, null) } }
            Card("Model for videos") { VideoModelPicker(state.videoModels, c.videoModel.ifBlank { "google/veo-3.1-lite" }, onVideoModel) }
            Card("Recent cloud use") {
                if (c.recent.isEmpty()) Text("Nothing yet.", color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium)
                c.recent.take(15).forEach { r ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                        Text((when (r.kind) { "image" -> "🎨 "; "video" -> "🎬 "; else -> "🧠 " }) + r.model.substringAfter('/'), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        Text("$" + "%.4f".format(r.cost), style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
                        Spacer(Modifier.width(8.dp))
                        Text(DateFormat.getTimeInstance(DateFormat.SHORT).format(Date((r.ts * 1000).toLong())), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun VideoModelPicker(models: List<info.thewiderlens.clara.data.VideoModel>, current: String, onPick: (String) -> Unit) {
    var showAll by remember { mutableStateOf(false) }
    Text("Clara plans the shots and shows you the price before anything renders. Prices are estimates for a 6-second 720p clip.",
        style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
    Spacer(Modifier.height(8.dp))
    if (models.isEmpty()) { Text("Loading models…", style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted); return }
    val chosen = models.firstOrNull { it.id == current }
    val shown = if (showAll) models else (listOfNotNull(chosen) + models.filter { it.id != current }.take(5))
    shown.forEach { m ->
        val on = m.id == current
        Row(
            Modifier.fillMaxWidth().padding(vertical = 2.dp).clip(RoundedCornerShape(12.dp))
                .then(if (on) Modifier.background(ClaraColors.Raised) else Modifier).clickable { onPick(m.id) }
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(m.name.substringAfter(": "), style = MaterialTheme.typography.bodyLarge)
                Text(m.id + (if (m.animatesImages) " · can animate pictures" else ""), style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
            }
            Text(m.perSecond?.let { "≈ $" + "%.2f".format(it * 6) } ?: "—", style = MaterialTheme.typography.bodyMedium,
                color = if (on) ClaraColors.Cyan else ClaraColors.Text)
            if (on) { Spacer(Modifier.width(6.dp)); Text("✓", color = ClaraColors.Cyan) }
        }
    }
    TextButton(onClick = { showAll = !showAll }) { Text(if (showAll) "Show fewer" else "Show all ${models.size} video models", color = ClaraColors.Cyan) }
}
