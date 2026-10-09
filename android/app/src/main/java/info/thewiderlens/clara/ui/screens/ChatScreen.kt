package info.thewiderlens.clara.ui.screens

import info.thewiderlens.clara.data.readBounded

import androidx.compose.foundation.border
import kotlinx.coroutines.launch
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.TextButton
import androidx.compose.material3.AlertDialog
import android.app.Activity
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.Link
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ApprovalCard
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.ClaraIcons
import info.thewiderlens.clara.ui.components.IdeaChip
import info.thewiderlens.clara.ui.components.MessageBubble
import info.thewiderlens.clara.ui.components.Mood
import info.thewiderlens.clara.ui.components.WorkingRow
import info.thewiderlens.clara.ui.moodOf
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors
import java.time.LocalTime

private val IDEAS = listOf(
    "What's the weather right now?",
    "What's using the most memory on my PC?",
    "Clean up my Downloads folder",
    "Remind me in an hour to stretch",
    "Find the best budget 24GB GPU",
    "Every morning at 8, send me the news",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    state: UiState,
    onSend: (String) -> Unit,
    onStop: () -> Unit,
    onAnswer: (Approval, String) -> Unit,
    onNewChat: () -> Unit,
    onOpen: (String) -> Unit,
    onHideLive: () -> Unit,
    onAssistant: () -> Unit,
    onWatch: () -> Unit = {},
    api: info.thewiderlens.clara.data.BridgeApi? = null,
    onTakeOver: () -> Unit = onWatch,
    onVault: (info.thewiderlens.clara.data.VaultRequest, Boolean) -> Unit = { _, _ -> },
    onApi: (info.thewiderlens.clara.data.ApiRequest, String) -> Unit = { _, _ -> },
    onCloud: (info.thewiderlens.clara.data.CloudRequest, String) -> Unit = { _, _ -> },
    onBudget: (info.thewiderlens.clara.data.BudgetSuggestion, Boolean) -> Unit = { _, _ -> },
    loadImage: (suspend (String) -> ByteArray?)? = null,
    onRefreshChats: () -> Unit = {},
    onDelete: (String) -> Unit = {},
    onAttach: (name: String, bytes: ByteArray, mime: String) -> Unit = { _, _, _ -> },
    onRemoveDraft: (Long) -> Unit = {},
    onVoice: () -> Unit = {},
) {
    var input by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(state.retryText) {
        if (state.retryText.isNotBlank()) input = if (input.isBlank()) state.retryText else input + "\n" + state.retryText
    }
    var showHistory by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf<info.thewiderlens.clara.data.Conversation?>(null) }
    val list = rememberLazyListState()
    val pendingHere = state.pending.filter { it.conversationId == state.conversationId || it.conversationId == null }
    val lastMsg = state.messages.lastOrNull()
    val chips = if (lastMsg != null && lastMsg.role == "assistant" && !state.working) lastMsg.suggestions else emptyList()
    val itemCount = (if (chips.isNotEmpty()) 1 else 0) + (if (state.help != null) 1 else 0) + state.messages.size + pendingHere.size + state.vaultRequests.size + state.apiRequests.size + state.cloudRequests.size + state.budgetSuggestions.size + (if (state.working) 1 else 0)
    // to the very bottom of the last item (a long reply or a browser card is taller than the screen)
    LaunchedEffect(itemCount, state.streaming.length / 80) {
        val lastVisible = list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
        if (itemCount > 0 && !list.isScrollInProgress && lastVisible >= itemCount - 3)
            list.scrollToItem(itemCount - 1, scrollOffset = 100_000)
    }
    var celebrating by remember { mutableStateOf(false) }
    LaunchedEffect(state.doneAt) { if (state.doneAt > 0) { celebrating = true; kotlinx.coroutines.delay(2500); celebrating = false } }
    val mood = moodOf(state, celebrating)
    val keyboardOpen = WindowInsets.ime.getBottom(LocalDensity.current) > 0

    val dictation = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        if (r.resultCode == Activity.RESULT_OK) {
            val heard = r.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!heard.isNullOrBlank()) input = (input.trimEnd() + " " + heard).trim()
        }
    }

    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    fun readPicked(uri: android.net.Uri?) {
        uri ?: return
        scope.launch {
            val cr = context.contentResolver
            val picked = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                runCatching {
                    val name = cr.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                        if (c.moveToFirst()) c.getString(0) else null
                    } ?: "file"
                    Triple(name, cr.openInputStream(uri)!!.use { it.readBounded() }, cr.getType(uri) ?: "application/octet-stream")
                }.getOrNull()
            }
            if (picked == null) android.widget.Toast.makeText(context, "Couldn't read that file", android.widget.Toast.LENGTH_SHORT).show()
            else if (picked.second.size > 25 * 1024 * 1024 && !picked.third.startsWith("image/"))
                android.widget.Toast.makeText(context, "That file is over 25 MB", android.widget.Toast.LENGTH_SHORT).show()
            else onAttach(picked.first, picked.second, picked.third)
        }
    }
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { readPicked(it) }
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { readPicked(it) }
    var attachMenu by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().imePadding()) {
        // Header: chats, name + connection, new chat, assistant menu
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { showHistory = true }) { Icon(Icons.Filled.Menu, "Chats", tint = ClaraColors.Muted) }
            Column(Modifier.weight(1f)) {
                Text("Clara", style = MaterialTheme.typography.titleMedium)
                val (dot, label) = when (state.link) {
                    Link.Online -> ClaraColors.Ok to (if (state.via == "remote") "On your computer · via Tailscale" else "On your computer")
                    Link.Connecting -> ClaraColors.Cyan to "Connecting…"
                    Link.Offline -> ClaraColors.Danger to "Can't reach your computer"
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(dot))
                    Spacer(Modifier.width(5.dp))
                    Text(label, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
                }
            }
            IconButton(onClick = onNewChat) { Icon(Icons.Filled.Add, "New chat", tint = ClaraColors.Muted) }
            Box(Modifier.padding(end = 6.dp).size(40.dp).clip(CircleShape).background(ClaraColors.Raised).clickable(onClick = onAssistant), contentAlignment = Alignment.Center) {
                ClaraCharacter(if (mood == Mood.Sleeping) Mood.Sleeping else Mood.Idle, size = 38.dp)
            }
        }

        // Stage: Clara herself, at the top of the chat, doing whatever she's doing
        val hasChat = state.messages.isNotEmpty() || state.working || state.vaultRequests.isNotEmpty() || state.apiRequests.isNotEmpty() || state.cloudRequests.isNotEmpty()
        AnimatedVisibility(visible = hasChat) {
            Column(Modifier.fillMaxWidth().padding(bottom = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                // she stays while you type, just smaller, so the chat keeps its room
                val size by androidx.compose.animation.core.animateDpAsState(if (keyboardOpen) 64.dp else 118.dp, label = "clara-size")
                ClaraCharacter(mood, size = size)
                Text(
                    when (mood) {
                        Mood.Waiting -> "Needs your OK"
                        Mood.Done -> "Done!"
                        Mood.Sleeping -> "Can't reach your computer"
                        Mood.Idle -> " "
                        else -> state.status.ifBlank { "Working on it…" }
                    },
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                    maxLines = 2, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.padding(horizontal = 24.dp),
                )
                if (state.working && (mood == Mood.Browsing || state.showLive)) {   // only when her browser is really open, not while she searches
                    Text(
                        "●  Watch live", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Text,
                        modifier = Modifier.padding(top = 6.dp).clip(RoundedCornerShape(12.dp)).background(ClaraBrush.bubble)
                            .clickable(onClick = onWatch).padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (!hasChat) {
                Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                    if (!keyboardOpen) ClaraCharacter(mood, size = 190.dp)
                    Spacer(Modifier.height(12.dp))
                    Text(greeting(), style = MaterialTheme.typography.headlineMedium)
                    Spacer(Modifier.height(6.dp))
                    Text("What can I take off your plate?", style = MaterialTheme.typography.bodyLarge, color = ClaraColors.Muted)
                    Spacer(Modifier.height(24.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        IDEAS.forEach { IdeaChip(it) { onSend(it) } }
                    }
                }
            } else {
                LazyColumn(state = list, contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), modifier = Modifier.fillMaxSize()) {
                    items(state.messages, key = { it.id }) {
                        MessageBubble(it, loadImage, onOpenBrowser = onWatch, onChoose = if (state.working) null else onSend)
                    }
                    if (chips.isNotEmpty()) item("chips-" + lastMsg!!.id) { SuggestionChips(chips) { onSend(it) } }
                    items(pendingHere, key = { "a-" + it.id }) { a -> ApprovalCard(a) { onAnswer(a, it) } }
                    items(state.vaultRequests, key = { "v-" + it.id }) { r -> info.thewiderlens.clara.ui.components.VaultCard(r) { ok -> onVault(r, ok) } }
                    items(state.apiRequests, key = { "k-" + it.id }) { r -> info.thewiderlens.clara.ui.components.ApiRequestCard(r) { c -> onApi(r, c) } }
                    items(state.cloudRequests, key = { "c-" + it.id }) { r -> info.thewiderlens.clara.ui.components.CloudRequestCard(r) { c -> onCloud(r, c) } }
                    items(state.budgetSuggestions, key = { "b-" + it.id }) { b -> info.thewiderlens.clara.ui.components.BudgetCard(b) { ok -> onBudget(b, ok) } }
                    if (state.working) item("working") {
                        Column {
                            WorkingRow(state.streaming)
                            if (state.showLive || mood == Mood.Browsing) info.thewiderlens.clara.ui.components.LiveBrowserCard(api, onWatch)
                        }
                    }
                    // last, so it's what the chat scrolls to: Clara is waiting on the user
                    state.help?.let { h -> item("help-" + h.id) { info.thewiderlens.clara.ui.components.HelpCard(h.reason, onTakeOver) } }
                }
                // Scrolled up: a small arrow above the type box jumps back to the newest message (like the Claude app)
                val awayFromBottom by remember { androidx.compose.runtime.derivedStateOf { list.canScrollForward } }
                val jump = androidx.compose.runtime.rememberCoroutineScope()
                androidx.compose.animation.AnimatedVisibility(
                    awayFromBottom, modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 10.dp),
                    enter = androidx.compose.animation.fadeIn() + androidx.compose.animation.scaleIn(),
                    exit = androidx.compose.animation.fadeOut() + androidx.compose.animation.scaleOut(),
                ) {
                    Box(
                        Modifier.size(40.dp).clip(CircleShape).background(ClaraColors.Raised).border(1.dp, ClaraColors.Line, CircleShape)
                            .clickable {
                                jump.launch {
                                    val far = itemCount - 1 - (list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) > 15
                                    if (far) list.scrollToItem((itemCount - 4).coerceAtLeast(0))   // a long way up: jump most of it
                                    list.animateScrollToItem((itemCount - 1).coerceAtLeast(0), scrollOffset = 100_000)
                                }
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Filled.KeyboardArrowDown, "Jump to the newest message", tint = ClaraColors.Text)
                    }
                }
            }
        }

        // Clara still busy in another chat: say so here, so this chat doesn't look like she's ignoring you
        state.conversations.firstOrNull { it.activeRun != null && it.id != state.conversationId }?.let { busy ->
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp).clip(RoundedCornerShape(14.dp))
                    .background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(14.dp))
                    .clickable { onOpen(busy.id) }.padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                androidx.compose.material3.CircularProgressIndicator(Modifier.size(14.dp), color = ClaraColors.Cyan, strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text("Clara is still working in “${busy.title.take(28)}”", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f),
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("Open ›", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
            }
        }

        // Picked photos/files waiting to be sent
        if (state.drafts.isNotEmpty()) {
            androidx.compose.foundation.lazy.LazyRow(
                Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(state.drafts, key = { it.id }) { d -> DraftChip(d) { onRemoveDraft(d.id) } }
            }
        }

        // Composer: attach, dictation, text, send / stop
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Box {
                IconButton(onClick = { attachMenu = true }) { Icon(ClaraIcons.Attach, "Attach", tint = ClaraColors.Muted) }
                androidx.compose.material3.DropdownMenu(expanded = attachMenu, onDismissRequest = { attachMenu = false }, containerColor = ClaraColors.Panel) {
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("Photo") }, leadingIcon = { Icon(ClaraIcons.Photo, null, tint = ClaraColors.Cyan) },
                        onClick = { attachMenu = false; photoPicker.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                    )
                    androidx.compose.material3.DropdownMenuItem(
                        text = { Text("File") }, leadingIcon = { Icon(ClaraIcons.Doc, null, tint = ClaraColors.Cyan) },
                        onClick = { attachMenu = false; filePicker.launch(arrayOf("*/*")) },
                    )
                }
            }
            TextField(
                value = input, onValueChange = { input = it },
                placeholder = { Text("Message Clara…") },
                modifier = Modifier.weight(1f),
                shape = RoundedCornerShape(26.dp),
                maxLines = 5,
                trailingIcon = {
                    IconButton(onClick = {
                        dictation.launch(
                            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                                .putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to Clara"),
                        )
                    }) { Icon(ClaraIcons.Mic, "Dictate", tint = ClaraColors.Muted) }
                },
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = ClaraColors.Raised, unfocusedContainerColor = ClaraColors.Raised,
                    focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                    cursorColor = ClaraColors.Cyan,
                ),
            )
            Spacer(Modifier.width(8.dp))
            val uploading = state.drafts.any { it.path == null && !it.failed }
            val hasFiles = state.drafts.any { it.path != null }
            val canSend = (input.isNotBlank() || hasFiles) && !uploading && state.drafts.none { it.failed } && !state.working && state.link == Link.Online
            val voiceButton = !canSend && !state.working && input.isBlank() && state.drafts.isEmpty()  // empty composer: talk instead
            Box(
                Modifier.size(50.dp).clip(CircleShape)
                    .background(if (state.working) ClaraBrush.approval else ClaraBrush.bubble)
                    .clickable(enabled = canSend || (state.working && !state.stopping) || voiceButton) {
                        if (canSend) { onSend(input.trim()); input = "" } else if (voiceButton) onVoice() else onStop()
                    },
                contentAlignment = Alignment.Center,
            ) {
                if (voiceButton) Icon(ClaraIcons.Waveform, "Voice mode", tint = ClaraColors.Text)
                else if (state.stopping) androidx.compose.material3.CircularProgressIndicator(Modifier.size(22.dp), color = ClaraColors.Text, strokeWidth = 2.dp)
                else if (state.working) Icon(Icons.Filled.Close, "Stop", tint = ClaraColors.Text)
                else Icon(Icons.AutoMirrored.Filled.Send, "Send", tint = ClaraColors.Text.copy(alpha = if (canSend) 1f else 0.4f))
            }
        }
    }

    if (showHistory) {
        LaunchedEffect(Unit) { onRefreshChats() }   // always the PC's current list (it once stayed empty after a network switch)
        ModalBottomSheet(onDismissRequest = { showHistory = false }, containerColor = ClaraColors.Panel) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Chats", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                Text("+ New chat", color = ClaraColors.Cyan, modifier = Modifier.clickable { onNewChat(); showHistory = false })
            }
            LazyColumn(Modifier.fillMaxWidth().height(460.dp)) {
                items(state.conversations, key = { it.id }) { c ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onOpen(c.id); showHistory = false }
                            .background(if (c.id == state.conversationId) ClaraColors.Raised else Color.Transparent)
                            .padding(horizontal = 20.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(c.title, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        if (c.id != info.thewiderlens.clara.ui.NOTIFICATIONS_CONVERSATION && c.activeRun == null) {
                            IconButton(onClick = { confirmDelete = c }, modifier = Modifier.size(32.dp)) {
                                Icon(Icons.Filled.Delete, "Delete chat", tint = ClaraColors.Muted, modifier = Modifier.size(20.dp))
                            }
                        }
                    }
                    HorizontalDivider(color = ClaraColors.Line.copy(alpha = 0.4f))
                }
            }
        }
    }

    confirmDelete?.let { c ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            containerColor = ClaraColors.Panel,
            title = { Text("Delete this chat?") },
            text = { Text("\"${c.title}\" and its messages will be removed. Clara keeps what she's learned about you.") },
            confirmButton = { TextButton(onClick = { onDelete(c.id); confirmDelete = null }) { Text("Delete", color = ClaraColors.Magenta) } },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Cancel") } },
        )
    }
}

private fun greeting(): String = when (LocalTime.now().hour) {
    in 5..11 -> "Good morning"
    in 12..16 -> "Good afternoon"
    else -> "Good evening"
}

@Composable
private fun DraftChip(d: info.thewiderlens.clara.ui.Draft, onRemove: () -> Unit) {
    Box(Modifier.size(72.dp).clip(RoundedCornerShape(14.dp)).background(ClaraColors.Raised)) {
        if (d.preview != null) {
            androidx.compose.foundation.Image(d.preview, d.name, contentScale = androidx.compose.ui.layout.ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else {
            Column(Modifier.fillMaxSize().padding(6.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Icon(ClaraIcons.Doc, null, tint = ClaraColors.Cyan, modifier = Modifier.size(24.dp))
                Text(d.name, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (d.path == null && !d.failed) Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f)), contentAlignment = Alignment.Center) {
            androidx.compose.material3.CircularProgressIndicator(Modifier.size(22.dp), color = ClaraColors.Cyan, strokeWidth = 2.dp)
        }
        if (d.failed) Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.6f)), contentAlignment = Alignment.Center) {
            Text("Failed", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Magenta)
        }
        Box(
            Modifier.align(Alignment.TopEnd).padding(3.dp).size(20.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.7f)).clickable(onClick = onRemove),
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.Close, "Remove", tint = Color.White, modifier = Modifier.size(14.dp)) }
    }
}

/** Tap-to-send replies Clara offers under her latest message (check-ins, daily suggestions). */
@Composable
private fun SuggestionChips(chips: List<String>, onPick: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 4.dp, top = 2.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        chips.forEach { c ->
            Text(
                c, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Text,
                modifier = Modifier.clip(RoundedCornerShape(18.dp)).border(1.dp, ClaraColors.Violet, RoundedCornerShape(18.dp))
                    .background(ClaraColors.Panel).clickable { onPick(c) }.padding(horizontal = 14.dp, vertical = 9.dp),
            )
        }
    }
}
