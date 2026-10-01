package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.CharacterStyle
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.components.Mood
import info.thewiderlens.clara.ui.components.hex
import info.thewiderlens.clara.ui.theme.ClaraColors
import kotlinx.coroutines.delay

private val PREVIEW_MOODS = listOf(Mood.Idle, Mood.Working, Mood.Thinking, Mood.Talking, Mood.Done, Mood.Waiting, Mood.Sleeping)
private val MOOD_LABEL = mapOf(Mood.Idle to "Idle", Mood.Working to "Working", Mood.Thinking to "Thinking", Mood.Talking to "Talking",
    Mood.Done to "Done!", Mood.Waiting to "Needs your OK", Mood.Sleeping to "Asleep")
private val PALETTES = listOf(
    listOf("#58DBFB", "#2F6BFF", "#5B3CF5", "#D53CD1"), listOf("#FFB36B", "#FF6B6B", "#C2185B"), listOf("#B8F2E6", "#5ED6B4", "#1BA784"),
    listOf("#F8B4D9", "#C084FC", "#8B5CF6"), listOf("#CBD5E1", "#64748B", "#334155"), listOf("#FDE68A", "#F59E0B", "#B45309"),
    listOf("#A78BFA", "#6D28D9", "#312E81"), listOf("#38BDF8", "#1D4ED8", "#0F172A"), listOf("#86EFAC", "#22C55E", "#166534"),
    listOf("#FCA5A5", "#EF4444", "#7F1D1D"),
)
private val ACCENTS = listOf("#D53CD1", "#FF5FA2", "#F43F5E", "#DC2626", "#F59E0B", "#22C55E", "#22D3EE", "#2F6BFF", "#E2E8F0", "#0B0B1C")
private val NICE = mapOf("cat_ears" to "Cat ears", "bunny_ears" to "Bunny ears", "sunglasses" to "Sunglasses", "curl" to "Logo curl")

private fun nice(s: String) = NICE[s] ?: s.replace('_', ' ').replaceFirstChar { it.uppercase() }

/** How Clara looks: presets, your own tweaks, and undo. Clara can restyle herself too ("make yourself purple"). */
@Composable
fun LookPage(
    state: UiState, onRefresh: () -> Unit, onPreset: (String) -> Unit, onStyle: (CharacterStyle) -> Unit, onUndo: () -> Unit, onBack: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    val view = state.character
    val style = view.style
    var moodIdx by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) { while (true) { delay(2600); moodIdx = (moodIdx + 1) % PREVIEW_MOODS.size } }
    val mood = PREVIEW_MOODS[moodIdx]

    PageScaffold("Clara's look", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(ClaraColors.Panel).padding(vertical = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                ClaraCharacter(mood, 170.dp, style = style)
                Text(style.name, style = MaterialTheme.typography.titleMedium)
                Text(MOOD_LABEL[mood] ?: "", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onUndo, enabled = view.canUndo, shape = RoundedCornerShape(14.dp)) { Text("Undo") }
                    OutlinedButton(onClick = { onPreset("Original") }, shape = RoundedCornerShape(14.dp)) { Text("Original") }
                }
            }
            Text("Tip: you can also just ask her, like “make yourself purple with cat ears” or “dress up cozy for winter”.",
                style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted)

            Section("Looks") {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    view.presets.forEach { (name, p) ->
                        val on = name == style.name
                        Column(
                            Modifier.width(86.dp).clip(RoundedCornerShape(16.dp)).background(if (on) ClaraColors.Raised else Color.Transparent)
                                .border(1.dp, if (on) ClaraColors.Cyan else ClaraColors.Line, RoundedCornerShape(16.dp)).clickable { onPreset(name) }.padding(6.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            ClaraCharacter(Mood.Idle, 70.dp, style = p)
                            Text(name, style = MaterialTheme.typography.labelMedium, textAlign = TextAlign.Center)
                        }
                    }
                }
            }

            Section("Colors") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    PALETTES.forEach { pal ->
                        val on = pal.map { it.uppercase() } == style.body.map { it.uppercase() }
                        Box(Modifier.size(40.dp).clip(CircleShape).background(Brush.linearGradient(pal.mapNotNull(::hex)))
                            .border(if (on) 3.dp else 1.dp, if (on) Color.White else ClaraColors.Line, CircleShape)
                            .clickable { onStyle(style.copy(body = pal, halo = listOf(pal.last(), pal.first()), hairColors = listOf(pal.first(), pal.last()), name = "Custom")) })
                    }
                }
            }
            Section("Shape") { Chips(view.options.shape, listOf(style.shape)) { onStyle(style.copy(shape = it, name = "Custom")) } }
            Section("Hair") { Chips(view.options.hair, listOf(style.hair)) { onStyle(style.copy(hair = it, name = "Custom")) } }
            Section("Eyes") { Chips(view.options.eyes, listOf(style.eyes)) { onStyle(style.copy(eyes = it, name = "Custom")) } }
            Section("Accessories (up to 3)") {
                Chips(view.options.accessories, style.accessories) { a ->
                    val next = if (a in style.accessories) style.accessories - a else (style.accessories + a).takeLast(3)
                    onStyle(style.copy(accessories = next, name = "Custom"))
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ACCENTS.forEach { c ->
                        val on = c.equals(style.accessoryColor, true)
                        Box(Modifier.size(28.dp).clip(CircleShape).background(hex(c) ?: Color.Gray)
                            .border(if (on) 3.dp else 1.dp, if (on) Color.White else ClaraColors.Line, CircleShape)
                            .clickable { onStyle(style.copy(accessoryColor = c, name = "Custom")) })
                    }
                }
            }
            Section("Blush") {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("None", style = MaterialTheme.typography.labelMedium, color = if (style.cheeks == null) ClaraColors.Cyan else ClaraColors.Muted,
                        modifier = Modifier.clickable { onStyle(style.copy(cheeks = null, name = "Custom")) }.padding(end = 4.dp))
                    listOf("#D53CD1", "#FF5FA2", "#F87171", "#FF9AA2", "#FBBF24").forEach { c ->
                        Box(Modifier.size(26.dp).clip(CircleShape).background(hex(c) ?: Color.Gray)
                            .border(if (c.equals(style.cheeks, true)) 3.dp else 1.dp, if (c.equals(style.cheeks, true)) Color.White else ClaraColors.Line, CircleShape)
                            .clickable { onStyle(style.copy(cheeks = c, name = "Custom")) })
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(14.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun Chips(options: List<String>, selected: List<String>, onPick: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { o ->
            val on = o in selected
            Text(nice(o), style = MaterialTheme.typography.bodyMedium, color = if (on) Color.White else ClaraColors.Text,
                modifier = Modifier.clip(RoundedCornerShape(14.dp))
                    .then(if (on) Modifier.background(Brush.linearGradient(listOf(ClaraColors.Blue, ClaraColors.Violet))) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(14.dp)))
                    .clickable { onPick(o) }.padding(horizontal = 12.dp, vertical = 7.dp))
        }
    }
}
