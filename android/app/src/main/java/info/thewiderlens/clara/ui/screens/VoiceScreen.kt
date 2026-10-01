package info.thewiderlens.clara.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.ClaraIcons
import info.thewiderlens.clara.ui.components.Mood
import info.thewiderlens.clara.ui.moodOf
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors
import info.thewiderlens.clara.voice.SentenceSplitter
import info.thewiderlens.clara.voice.VoicePhase
import info.thewiderlens.clara.voice.VoiceSession

/**
 * Voice mode: talk to Clara hands-free. She listens, answers out loud with her own voice, then listens again.
 * Everything said lands in the current chat as normal messages.
 */
@Composable
fun VoiceScreen(
    state: UiState,
    onSend: (String) -> Unit,
    speech: suspend (String) -> ByteArray?,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val session = remember { VoiceSession(context, scope, speech) }
    val phase by session.phase.collectAsState()
    val heard by session.heardSoFar.collectAsState()
    val caption by session.caption.collectAsState()
    val level by session.level.collectAsState()
    val problem by session.problem.collectAsState()

    // Which reply we're speaking: messages that existed before the user spoke are ignored.
    var waitingSince by remember { mutableStateOf<Set<String>?>(null) }
    var acknowledged by remember { mutableStateOf(false) }
    var handsFree by remember { mutableStateOf(true) }
    val splitter = remember { SentenceSplitter() }

    var micAllowed by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
    }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        micAllowed = ok
        if (ok) session.listen()
    }

    val view = LocalView.current
    val latestMessages by androidx.compose.runtime.rememberUpdatedState(state.messages)
    val latestSend by androidx.compose.runtime.rememberUpdatedState(onSend)
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        session.onHeard = { text ->
            waitingSince = latestMessages.map { it.id }.toSet()
            acknowledged = false
            splitter.reset()
            latestSend(text)
        }
        session.onSpokenAll = { if (handsFree) session.listen() }
        if (micAllowed) session.listen() else askMic.launch(Manifest.permission.RECORD_AUDIO)
        onDispose {
            view.keepScreenOn = false
            session.release()
        }
    }

    // When a request goes to Clara's agent (slow: tools + thinking), say something right away instead of dead air.
    LaunchedEffect(Unit) { session.prepare(ACKS_TASK + ACKS_SCHEDULE) }
    LaunchedEffect(state.messages) {
        val before = waitingSince ?: return@LaunchedEffect
        if (acknowledged) return@LaunchedEffect
        val mine = state.messages.lastOrNull { it.role == "user" && it.id !in before && !it.id.startsWith("local-") } ?: return@LaunchedEffect
        acknowledged = true
        when (mine.route) {
            "task" -> session.say(ACKS_TASK.random())
            "schedule" -> session.say(ACKS_SCHEDULE.random())
        }
    }

    // Stream Clara's reply into speech as sentences complete.
    LaunchedEffect(state.streaming) {
        if (waitingSince != null && state.streaming.isNotBlank()) splitter.feed(state.streaming, final = false).forEach(session::say)
    }
    LaunchedEffect(state.messages.size) {
        val before = waitingSince ?: return@LaunchedEffect
        val reply = state.messages.lastOrNull { it.role == "assistant" && it.id !in before } ?: return@LaunchedEffect
        waitingSince = null
        splitter.finish(reply.content.trim()).forEach(session::say)
        session.finishReply()
    }

    val needsOk = state.pending.isNotEmpty() || state.vaultRequests.isNotEmpty() || state.apiRequests.isNotEmpty() || state.cloudRequests.isNotEmpty()
    val mood = when {
        phase == VoicePhase.Speaking -> Mood.Talking
        phase == VoicePhase.Listening -> Mood.Idle
        phase == VoicePhase.Thinking || waitingSince != null -> moodOf(state).let { if (it == Mood.Idle) Mood.Thinking else it }
        else -> Mood.Idle
    }
    val status = when {
        needsOk -> "Clara needs your OK in the chat"
        phase == VoicePhase.Listening -> "Listening…"
        phase == VoicePhase.Speaking -> "Speaking — tap to interrupt"
        phase == VoicePhase.Thinking || waitingSince != null -> state.status.ifBlank { "Thinking…" }
        problem != null -> problem!!
        else -> "Tap to talk"
    }
    val pulse by animateFloatAsState(if (phase == VoicePhase.Listening) 1f + level * 0.35f else 1f, tween(90), label = "mic")

    Column(
        Modifier.fillMaxSize().background(ClaraColors.Black).padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Voice", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            Text(
                if (handsFree) "Hands-free" else "Tap to talk", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan,
                modifier = Modifier.clip(RoundedCornerShape(12.dp)).background(ClaraColors.Raised).clickable { handsFree = !handsFree }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            )
        }
        Spacer(Modifier.weight(0.6f))
        ClaraCharacter(mood, 220.dp)
        Spacer(Modifier.height(20.dp))
        Text(status, style = MaterialTheme.typography.titleMedium, color = if (needsOk) ClaraColors.Magenta else ClaraColors.Muted, textAlign = TextAlign.Center,
            modifier = if (needsOk) Modifier.clickable(onClick = onClose) else Modifier)
        Spacer(Modifier.height(16.dp))
        // live captions: what you're saying, then what Clara is saying
        Box(Modifier.fillMaxWidth().heightIn(min = 96.dp), contentAlignment = Alignment.TopCenter) {
            val text = when (phase) {
                VoicePhase.Speaking -> caption
                else -> heard
            }
            Text(
                text, style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center, maxLines = 4, overflow = TextOverflow.Ellipsis,
                color = if (phase == VoicePhase.Speaking) ClaraColors.Text else ClaraColors.Text.copy(alpha = 0.7f),
            )
        }
        Spacer(Modifier.weight(1f))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(36.dp)) {
            Box(
                Modifier.size(56.dp).clip(CircleShape).background(ClaraColors.Raised).clickable(onClick = onClose),
                contentAlignment = Alignment.Center,
            ) { Icon(Icons.Filled.Close, "End voice", tint = ClaraColors.Text) }
            Box(
                Modifier.size(88.dp).scale(pulse).clip(CircleShape)
                    .background(if (phase == VoicePhase.Listening) ClaraBrush.bubble else ClaraBrush.approval)
                    .border(2.dp, ClaraColors.Cyan.copy(alpha = if (phase == VoicePhase.Listening) 0.9f else 0.2f), CircleShape)
                    .clickable {
                        when (phase) {
                            VoicePhase.Listening -> session.stopListening()
                            VoicePhase.Speaking -> { waitingSince = null; session.listen() }  // interrupt Clara
                            else -> if (micAllowed) session.listen() else askMic.launch(Manifest.permission.RECORD_AUDIO)
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(if (phase == VoicePhase.Speaking) ClaraIcons.Waveform else ClaraIcons.Mic, "Talk", tint = ClaraColors.Text, modifier = Modifier.size(36.dp))
            }
            Spacer(Modifier.size(56.dp))
        }
        Spacer(Modifier.height(12.dp))
    }
}

private val ACKS_TASK = listOf("On it, give me a sec.", "Sure, let me work on that.", "Okay, one moment.", "Got it, working on it now.")
private val ACKS_SCHEDULE = listOf("Sure, one sec.", "Let me check.", "Okay, give me a moment.")
