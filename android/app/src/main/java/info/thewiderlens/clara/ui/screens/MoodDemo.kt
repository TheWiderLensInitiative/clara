package info.thewiderlens.clara.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.Mood
import info.thewiderlens.clara.ui.theme.ClaraColors
import kotlinx.coroutines.delay

private val LABELS = mapOf(
    Mood.Idle to "Hanging out", Mood.Thinking to "Thinking…", Mood.Talking to "Replying",
    Mood.Working to "Using the terminal…", Mood.Browsing to "Using the browser…", Mood.Searching to "Searching the web…",
    Mood.Scheduling to "Scheduling…", Mood.Waiting to "Needs your OK", Mood.Done to "Done!", Mood.Sleeping to "Can't reach your computer",
)

/** Cycles through every mood; launched with the `demo_moods` intent extra (for previews and recordings). */
@Composable
fun MoodDemo() {
    var i by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) { while (true) { delay(3500); i = (i + 1) % Mood.entries.size } }
    val mood = Mood.entries[i]
    Column(Modifier.fillMaxSize().background(ClaraColors.Black), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        ClaraCharacter(mood, size = 300.dp)
        Spacer(Modifier.height(24.dp))
        Text(LABELS[mood] ?: "", style = MaterialTheme.typography.headlineMedium)
        Text(mood.name, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
    }
}
