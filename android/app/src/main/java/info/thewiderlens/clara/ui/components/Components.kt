package info.thewiderlens.clara.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.runtime.getValue
import androidx.compose.foundation.layout.offset
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.LinearEasing
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.data.Message
import info.thewiderlens.clara.ui.theme.ClaraBrush
import info.thewiderlens.clara.ui.theme.ClaraColors

@Composable
fun GradientButton(text: String, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(ClaraBrush.bubble)
            .alpha(if (enabled) 1f else 0.4f)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(vertical = 15.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, style = MaterialTheme.typography.titleMedium, color = ClaraColors.Text) }
}

/** Minimal markdown: **bold** and `code`, which is what Clara's replies mostly use. */
fun markdown(raw: String): AnnotatedString = buildAnnotatedString {
    // checklists and bullets read better as symbols than as raw markdown
    val text = raw.replace(Regex("""(?m)^(\s*)[-*] \[ \] """), "$1☐ ")
        .replace(Regex("""(?m)^(\s*)[-*] \[[xX]\] """), "$1☑ ")
        .replace(Regex("""(?m)^(\s*)[-*] (?=\S)"""), "$1• ")
    val rx = Regex("""\*\*(.+?)\*\*|`([^`]+)`""")
    var i = 0
    for (m in rx.findAll(text)) {
        append(text.substring(i, m.range.first))
        val (bold, code) = m.destructured
        if (bold.isNotEmpty()) withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = ClaraColors.Cyan)) { append(bold) }
        else withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = ClaraColors.Raised)) { append(code) }
        i = m.range.last + 1
    }
    append(text.substring(i))
}

@kotlinx.serialization.Serializable
private data class ProductCard(val choice: Int = 0, val title: String = "", val price: String = "", val seller: String = "",
                               val store: String = "", val image: String = "", val rating: Double? = null, val reviews: Int? = null,
                               val url: String = "")

@Composable
private fun ProductCards(json: String, load: (suspend (String) -> ByteArray?)?, onChoose: ((String) -> Unit)?) {
    val cards = remember(json) {
        runCatching { kotlinx.serialization.json.Json { ignoreUnknownKeys = true }.decodeFromString<List<ProductCard>>(json) }.getOrDefault(emptyList())
    }
    var chosen by remember(json) { mutableStateOf<Int?>(null) }
    val context = androidx.compose.ui.platform.LocalContext.current
    androidx.compose.foundation.lazy.LazyRow(
        Modifier.padding(top = 6.dp).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 4.dp),
    ) {
        items(cards.size) { i ->
            val c = cards[i]
            Column(
                Modifier.width(196.dp).clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel)
                    .border(1.5.dp, if (chosen == c.choice) ClaraColors.Cyan else ClaraColors.Line, RoundedCornerShape(18.dp)),
            ) {
                ProductPhoto(c.image, load)
                Column(Modifier.padding(10.dp)) {
                    Text(c.title, style = MaterialTheme.typography.bodyMedium, maxLines = 2,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.height(40.dp))
                    Text(c.price, style = MaterialTheme.typography.titleMedium, color = ClaraColors.Text)
                    Text(c.seller.ifBlank { c.store }, style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted, maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    c.rating?.let { r ->
                        Text("★ " + "%.1f".format(r) + (c.reviews?.let { n -> " · $n reviews" } ?: ""), style = MaterialTheme.typography.labelSmall,
                            color = ClaraColors.Cyan)
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (onChoose != null && chosen == null) GradientButton("Choose", modifier = Modifier.weight(1f)) {
                            chosen = c.choice
                            onChoose("#${c.choice} · ${c.title.take(70)} · ${c.seller.ifBlank { c.store }} · ${c.price}")
                        } else Text(if (chosen == c.choice) "✓ Chosen" else " ", color = ClaraColors.Cyan,
                            style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
                        if (c.url.isNotBlank()) Text("View", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                            modifier = Modifier.padding(start = 8.dp).clickable {
                                runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(c.url))) }
                            })
                    }
                }
            }
        }
    }
}

@Composable
fun ProductPhoto(url: String, load: (suspend (String) -> ByteArray?)?, modifier: Modifier = Modifier.fillMaxWidth().height(150.dp)) {
    var bmp by remember(url) { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    LaunchedEffect(url) {
        if (url.isNotBlank() && load != null) bmp = runCatching { load(url) }.getOrNull()?.let {
            android.graphics.BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap()
        }
    }
    Box(modifier.background(Color.White), contentAlignment = Alignment.Center) {
        bmp?.let { Image(it, null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().padding(8.dp)) }
            ?: Text("🛍️", style = MaterialTheme.typography.headlineMedium)
    }
}

/** A file Clara made, under her reply: tap to read it in the Library's viewer. */
@Composable
private fun MadeFileCard(path: String, load: suspend (String) -> ByteArray?) {
    var open by remember { mutableStateOf(false) }
    val name = path.substringAfterLast('/')
    val ext = name.substringAfterLast('.', "").lowercase()
    val kind = when (ext) { "md", "txt", "csv", "json", "log", "py", "html", "sh", "yaml", "yml" -> "text"; "pdf" -> "pdf"; else -> "file" }
    Row(
        Modifier.padding(top = 6.dp, start = 4.dp).widthIn(max = 330.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp))
            .background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(14.dp))
            .clickable { open = true }.padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(when (kind) { "text" -> "📝"; "pdf" -> "📄"; else -> "📦" }, style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            Text("Saved in your Library · tap to open", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
        }
    }
    if (open) info.thewiderlens.clara.ui.screens.FileViewer(info.thewiderlens.clara.data.LibraryFile(path, name, kind = kind), load) { open = false }
}

@Composable
fun MessageBubble(m: Message, load: (suspend (String) -> ByteArray?)? = null, onOpenBrowser: () -> Unit = {},
                  onChoose: ((String) -> Unit)? = null) {
    val mine = m.role == "user"
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        if (mine) {
            // Clara reacts to a message she's taking on (👀 task, ⏰ reminder)
            val reaction = when (m.route) { "task" -> "👀"; "schedule" -> "⏰"; else -> null }
            Box(Modifier.padding(bottom = if (reaction != null) 12.dp else 0.dp)) {
                Column(horizontalAlignment = Alignment.End) {
                    m.attachments.forEach { p ->
                        if (isImagePath(p) && load != null) InlineImage(p, load, maxWidth = 240)
                        else if (isVideoPath(p) && load != null) InlineVideo(p, load, maxWidth = 240)
                        else Row(
                            Modifier.padding(vertical = 3.dp).clip(RoundedCornerShape(14.dp)).background(ClaraColors.Raised)
                                .padding(horizontal = 12.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            androidx.compose.material3.Icon(ClaraIcons.Doc, null, tint = ClaraColors.Cyan, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(p.substringAfterLast('/').replace(Regex("^\\d{8}-\\d{6}-"), ""), style = MaterialTheme.typography.bodyMedium,
                                maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 220.dp))
                        }
                    }
                    if (m.content.isNotBlank()) {
                        val context = androidx.compose.ui.platform.LocalContext.current
                        SelectionContainer {
                            Text(
                                m.content, style = MaterialTheme.typography.bodyLarge, color = ClaraColors.Text,
                                modifier = Modifier.widthIn(max = 300.dp)
                                    .background(ClaraBrush.bubble, RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp, bottomStart = 20.dp, bottomEnd = 6.dp))
                                    .padding(horizontal = 16.dp, vertical = 11.dp),
                            )
                        }
                        Text(
                            "Copy", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted,
                            modifier = Modifier.clickable { copyToClipboard(context, m.content) }.padding(top = 2.dp, end = 4.dp),
                        )
                    }
                }
                reaction?.let {
                    Text(
                        it, style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.align(Alignment.BottomStart).offset(x = (-6).dp, y = 14.dp)
                            .clip(CircleShape).background(ClaraColors.Raised).border(1.5.dp, ClaraColors.Black, CircleShape)
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
            }
        } else {
            val (text, images) = remember(m.content) { splitImages(m.content) }
            var reporting by remember { mutableStateOf(false) }
            Column {
                if (text.isNotBlank()) {
                    // Selectable text: long-press brings up Android's Copy. A clip() or a custom
                    // long-press here used to swallow that gesture, so nothing could be copied.
                    SelectionContainer {
                        Text(
                            markdown(text), style = MaterialTheme.typography.bodyLarge, color = ClaraColors.Text,
                            modifier = Modifier.widthIn(max = 330.dp).padding(horizontal = 4.dp, vertical = 6.dp),
                        )
                    }
                    val context = androidx.compose.ui.platform.LocalContext.current
                    Row(Modifier.padding(start = 4.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                        Text(
                            "Copy", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted,
                            modifier = Modifier.clickable { copyToClipboard(context, text) }.padding(vertical = 2.dp),
                        )
                        Text(
                            "Report", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted,
                            modifier = Modifier.clickable { reporting = true }.padding(vertical = 2.dp),
                        )
                    }
                }
                if (load != null) images.forEach { if (isVideoPath(it)) InlineVideo(it, load) else InlineImage(it, load) }
                // files Clara made or changed in this task (like Muse): a card under her reply that opens the file
                if (load != null) m.attachments.filter { it !in images }.forEach { p ->
                    if (isImagePath(p)) InlineImage(p, load) else if (isVideoPath(p)) InlineVideo(p, load) else MadeFileCard(p, load)
                }
                // products from a shopping search (like Muse): swipe the cards, tap Choose
                if (m.meta?.get("kind") == "products") m.meta["products"]?.let { ProductCards(it, load, onChoose) }
                val shot = m.meta?.get("browser")
                if (shot != null && load != null) BrowserSnapshotCard(shot, m.meta["browser_url"].orEmpty(), load, onOpenBrowser)
                // a post Clara prepared for a site that doesn't let apps post (Reddit): one tap opens it, the user posts it
                if (m.meta?.get("kind") == "share") m.meta["url"]?.let { url ->
                    val context = androidx.compose.ui.platform.LocalContext.current
                    GradientButton(m.meta["label"] ?: "Open", modifier = Modifier.padding(top = 4.dp, bottom = 6.dp).widthIn(max = 330.dp).fillMaxWidth()) {
                        runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) }
                    }
                }
            }
            if (reporting) ReportDialog(text) { reporting = false }
        }
    }
}

private fun copyToClipboard(context: android.content.Context, text: String) {
    context.getSystemService(android.content.ClipboardManager::class.java)
        .setPrimaryClip(android.content.ClipData.newPlainText("Clara", text))
    // Android 13 and later shows its own "copied" confirmation.
    if (android.os.Build.VERSION.SDK_INT < 33) {
        android.widget.Toast.makeText(context, "Copied", android.widget.Toast.LENGTH_SHORT).show()
    }
}

/** Reports go to the project's public issue tracker; there is no Clara server. The reply is only included if the user opts in. */
@Composable
private fun ReportDialog(text: String, onDone: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var include by remember { mutableStateOf(false) }
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDone,
        title = { Text("Report this reply") },
        text = {
            Column {
                Text(
                    "Was this reply offensive, harmful or wrong? Your report opens on the Clara project's GitHub, where it helps " +
                        "improve Clara's rules and models. GitHub reports are public.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Row(Modifier.padding(top = 12.dp).clickable { include = !include }, verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Checkbox(checked = include, onCheckedChange = { include = it })
                    Text("Include the reply's text", style = MaterialTheme.typography.bodyMedium)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val body = buildString {
                    append("**What was wrong with the reply?**\n\n\n")
                    if (include) append("**Clara's reply:**\n\n").append(text.take(1500).lines().joinToString("\n") { "> $it" }).append("\n")
                }
                val url = android.net.Uri.parse("https://github.com/TheWiderLensInitiative/clara/issues/new").buildUpon()
                    .appendQueryParameter("title", "Reported reply")
                    .appendQueryParameter("labels", "reported-reply")
                    .appendQueryParameter("body", body).build()
                runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, url)) }
                onDone()
            }) { Text("Report") }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel") } },
    )
}

private const val WORKSPACE = "/var/lib/clara/workspace/"
private val MEDIA_LINE = Regex("""[ \t]*MEDIA:\s*(\S+)""")
private val IMAGE_PATH = Regex("""(?:~/clara/workspace/|/var/lib/clara/workspace/)(\S+?\.(?:png|jpe?g|webp|gif|mp4|webm|mov|m4v))""", RegexOption.IGNORE_CASE)

fun isImagePath(p: String) = Regex("""(?i)\.(png|jpe?g|webp|gif)$""").containsMatchIn(p)
fun isVideoPath(p: String) = Regex("""(?i)\.(mp4|webm|mov|m4v)$""").containsMatchIn(p)

/** Pull image files out of Clara's reply: MEDIA: lines disappear from the text, and any picture in her workspace is shown inline. */
fun splitImages(content: String): Pair<String, List<String>> {
    val found = LinkedHashSet<String>()
    var text = MEDIA_LINE.replace(content) { mr ->
        val p = mr.groupValues[1].trimEnd('.', ',', ')', ';', '!', '`', '"', '\'')
        if (p.startsWith(WORKSPACE)) found += p.removePrefix(WORKSPACE) else if (!p.startsWith("/")) found += p
        ""
    }
    IMAGE_PATH.findAll(text).forEach { found += it.groupValues[1] }
    text = text.replace(Regex("""\n{3,}"""), "\n\n").trim()
    return text to found.filter { isImagePath(it) || isVideoPath(it) }
}

@Composable
private fun InlineImage(path: String, load: suspend (String) -> ByteArray?, maxWidth: Int = 300) {
    var bmp by remember(path) { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    var failed by remember(path) { mutableStateOf(false) }
    var full by remember { mutableStateOf(false) }
    LaunchedEffect(path) {
        val bytes = runCatching { load(path) }.getOrNull()
        bmp = bytes?.let { android.graphics.BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
        failed = bmp == null
    }
    val shape = RoundedCornerShape(18.dp)
    Box(
        Modifier.padding(horizontal = 4.dp, vertical = 6.dp).widthIn(max = maxWidth.dp).fillMaxWidth()
            .clip(shape).background(ClaraColors.Raised).clickable(enabled = bmp != null) { full = true },
        contentAlignment = Alignment.Center,
    ) {
        val b = bmp
        when {
            b != null -> Image(b, contentDescription = "Image from Clara", contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth())
            failed -> Text("Couldn't load ${path.substringAfterLast('/')}", style = MaterialTheme.typography.bodySmall, color = ClaraColors.Muted, modifier = Modifier.padding(16.dp))
            else -> Box(Modifier.fillMaxWidth().height(220.dp), contentAlignment = Alignment.Center) { TypingDots() }
        }
    }
    val b = bmp
    if (full && b != null) {
        androidx.compose.ui.window.Dialog(onDismissRequest = { full = false }, properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
            Box(Modifier.fillMaxSize().background(Color.Black).clickable { full = false }, contentAlignment = Alignment.Center) {
                Image(b, contentDescription = "Image from Clara", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
fun WorkingRow(streaming: String, onWatch: (() -> Unit)? = null) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        if (streaming.isNotBlank()) {
            SelectionContainer {
                Text(markdown(streaming), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(horizontal = 4.dp))
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TypingDots()
                if (onWatch != null) {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "●  Watch Clara's browser live", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Text,
                        modifier = Modifier.clip(RoundedCornerShape(12.dp)).background(ClaraBrush.bubble)
                            .clickable(onClick = onWatch).padding(horizontal = 12.dp, vertical = 7.dp),
                    )
                }
            }
        }
    }
}

/** Three dots bouncing in the ribbon colors, shown in the thread while Clara works (her status is on the stage above). */
@Composable
fun TypingDots() {
    val t = rememberInfiniteTransition(label = "dots")
    val phase by t.animateFloat(0f, 3f, infiniteRepeatable(tween(900, easing = LinearEasing)), label = "phase")
    Row(Modifier.padding(horizontal = 6.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        listOf(ClaraColors.Cyan, ClaraColors.Violet, ClaraColors.Magenta).forEachIndexed { i, c ->
            val lift = if (phase.toInt() == i) -5f else 0f
            Box(Modifier.offset(y = lift.dp).size(8.dp).clip(CircleShape).background(c))
        }
    }
}

@Composable
fun ApprovalCard(a: Approval, onAnswer: (String) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp)
            .border(BorderStroke(1.5.dp, ClaraBrush.approval), RoundedCornerShape(20.dp))
            .clip(RoundedCornerShape(20.dp)).background(ClaraColors.Panel).padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(ClaraColors.Magenta))
            Spacer(Modifier.width(8.dp))
            Text("Clara needs your OK", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Magenta)
        }
        Spacer(Modifier.height(8.dp))
        val preview = listOf("✉️", "📅", "🔌", "▶️").any { a.description.startsWith(it) }   // email / calendar: show exactly what will happen
        if (preview) {
            Text(a.description, style = MaterialTheme.typography.bodyLarge)
            a.command?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Text, maxLines = 14, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(ClaraColors.Black).padding(12.dp))
            }
        }
        val (summary, command) = a.description.split(": ", limit = 2).let { it[0] to it.getOrNull(1) }
        if (!preview) Text("$summary.", style = MaterialTheme.typography.bodyLarge)
        if (!preview) command?.let {
            Spacer(Modifier.height(8.dp))
            Text(
                it, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), color = ClaraColors.Muted,
                maxLines = 4, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(ClaraColors.Black).padding(10.dp),
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { onAnswer("deny") }, shape = RoundedCornerShape(12.dp)) { Text("Deny", color = ClaraColors.Text) }
            if ("session" in a.choices) TextButton(onClick = { onAnswer("session") }) { Text("Allow for this chat", color = ClaraColors.Cyan) }
            Spacer(Modifier.weight(1f))
            if ("once" in a.choices) GradientButton("Allow", modifier = Modifier.width(96.dp)) { onAnswer("once") }
        }
    }
}

@Composable
fun LiveView(bmp: ImageBitmap, onClose: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp).clip(RoundedCornerShape(18.dp))
            .border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).background(ClaraColors.Panel),
    ) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(ClaraColors.Ok))
            Spacer(Modifier.width(8.dp))
            Text("Live view · Clara's browser", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted, modifier = Modifier.weight(1f))
            Text("Hide", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, modifier = Modifier.clickable(onClick = onClose))
        }
        Image(bmp, contentDescription = "What Clara sees", contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
fun IdeaChip(text: String, onClick: () -> Unit) {
    Text(
        text, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Text,
        modifier = Modifier.clip(RoundedCornerShape(14.dp)).border(1.dp, ClaraColors.Line, RoundedCornerShape(14.dp))
            .background(ClaraColors.Panel).clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 10.dp),
    )
}

/** Clara asking to use one of the phone's saved logins. Allow requires fingerprint/PIN before anything leaves the phone. */
@Composable
fun VaultCard(r: info.thewiderlens.clara.data.VaultRequest, onAnswer: (Boolean) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp)
            .border(BorderStroke(1.5.dp, ClaraBrush.ribbon), RoundedCornerShape(20.dp))
            .clip(RoundedCornerShape(20.dp)).background(ClaraColors.Panel).padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("🔑", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(8.dp))
            Text("Clara wants to sign in", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        }
        Spacer(Modifier.height(8.dp))
        Text(r.name, style = MaterialTheme.typography.titleMedium)
        Text(
            "${r.username} · ${r.site.removePrefix("https://").removePrefix("http://").substringBefore('/')}",
            style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "Your password stays encrypted and is only unlocked for this one sign-in. Clara never sees it.",
            style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
        )
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { onAnswer(false) }, shape = RoundedCornerShape(12.dp)) { Text("Deny", color = ClaraColors.Text) }
            Spacer(Modifier.weight(1f))
            GradientButton("Allow with fingerprint", modifier = Modifier.width(210.dp)) { onAnswer(true) }
        }
    }
}

/** Clara asking to use one of your saved API keys. Changes show exactly what she wants to send. */
@Composable
fun ApiRequestCard(r: info.thewiderlens.clara.data.ApiRequest, onAnswer: (String) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp)
            .border(BorderStroke(1.5.dp, if (r.write) ClaraBrush.approval else ClaraBrush.ribbon), RoundedCornerShape(20.dp))
            .clip(RoundedCornerShape(20.dp)).background(ClaraColors.Panel).padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("🔌", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(8.dp))
            Text(if (r.write) "Clara wants to make a change with ${r.service}" else "Clara wants to use ${r.service}",
                style = MaterialTheme.typography.labelMedium, color = if (r.write) ClaraColors.Magenta else ClaraColors.Cyan)
        }
        Spacer(Modifier.height(8.dp))
        Text("${r.method}  ${r.path}", style = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace))
        Text(r.host.removePrefix("https://"), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
        if (r.body.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(r.body, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), color = ClaraColors.Muted,
                maxLines = 6, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(ClaraColors.Black).padding(10.dp))
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { onAnswer("deny") }, shape = RoundedCornerShape(12.dp)) { Text("Deny", color = ClaraColors.Text) }
            if ("chat" in r.choices) TextButton(onClick = { onAnswer("chat") }) { Text("This chat", color = ClaraColors.Cyan) }
            if ("always" in r.choices) TextButton(onClick = { onAnswer("always") }) { Text("Always", color = ClaraColors.Cyan) }
            Spacer(Modifier.weight(1f))
            GradientButton("Allow", modifier = Modifier.width(92.dp)) { onAnswer("once") }
        }
    }
}

/** Clara asking to call in a cloud model for the current task. */
@Composable
fun CloudRequestCard(r: info.thewiderlens.clara.data.CloudRequest, onAnswer: (String) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp)
            .border(BorderStroke(1.5.dp, ClaraBrush.ribbon), RoundedCornerShape(20.dp))
            .clip(RoundedCornerShape(20.dp)).background(ClaraColors.Panel).padding(16.dp),
    ) {
        if (r.kind == "video") { VideoApproval(r, onAnswer); return@Column }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (r.kind == "image") "🎨" else "☁️", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(8.dp))
            Text(if (r.kind == "image") "Clara wants to generate an image in the cloud" else "Clara wants help from a cloud model",
                style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        }
        Spacer(Modifier.height(8.dp))
        Text(r.model, style = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace))
        Text("This sends the task to OpenRouter. Today so far: $" + "%.2f".format(r.spentToday) +
            (r.cap?.let { " of $" + "%.2f".format(it) } ?: ""), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { onAnswer("deny") }, shape = RoundedCornerShape(12.dp)) { Text("Deny", color = ClaraColors.Text) }
            TextButton(onClick = { onAnswer("always") }) { Text("Always", color = ClaraColors.Cyan) }
            Spacer(Modifier.weight(1f))
            GradientButton("This task", modifier = Modifier.width(120.dp)) { onAnswer("task") }
        }
    }
}

/** Clara suggesting a daily cloud budget; only the user can accept it. */
@Composable
fun BudgetCard(b: info.thewiderlens.clara.data.BudgetSuggestion, onAnswer: (Boolean) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 6.dp).border(BorderStroke(1.5.dp, ClaraBrush.ribbon), RoundedCornerShape(20.dp))
            .clip(RoundedCornerShape(20.dp)).background(ClaraColors.Panel).padding(16.dp),
    ) {
        Text("💰  Clara suggests a daily cloud budget", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(6.dp))
        Text("$" + "%.2f".format(b.amount) + " per day", style = MaterialTheme.typography.titleMedium)
        if (b.reason.isNotBlank()) Text(b.reason, style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { onAnswer(false) }, shape = RoundedCornerShape(12.dp)) { Text("Decline", color = ClaraColors.Text) }
            Spacer(Modifier.weight(1f))
            GradientButton("Accept", modifier = Modifier.width(110.dp)) { onAnswer(true) }
        }
    }
}

/** Videos are approved one at a time, with the price up front. */
@Composable
private fun VideoApproval(r: info.thewiderlens.clara.data.CloudRequest, onAnswer: (String) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("🎬", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.width(8.dp))
        Text("Clara wants to make a video", style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
    }
    Spacer(Modifier.height(8.dp))
    Text(r.estimate?.let { "About $" + "%.2f".format(it) } ?: "Price unknown for this model", style = MaterialTheme.typography.headlineSmall)
    r.summary?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
    Text("Rendered in the cloud through OpenRouter. Today so far: $" + "%.2f".format(r.spentToday) +
        (r.cap?.let { " of $" + "%.2f".format(it) } ?: ""), style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted)
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(onClick = { onAnswer("deny") }, shape = RoundedCornerShape(12.dp)) { Text("Not now", color = ClaraColors.Text) }
        Spacer(Modifier.weight(1f))
        GradientButton("Make it", modifier = Modifier.width(130.dp)) { onAnswer("once") }
    }
}

/** A video in the chat: its poster frame (made on the PC next to the .mp4) with a play button; plays full screen. */
@Composable
fun InlineVideo(path: String, load: suspend (String) -> ByteArray?, maxWidth: Int = 300) {
    var posterBmp by remember(path) { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
    var playing by remember { mutableStateOf(false) }
    LaunchedEffect(path) {
        val bytes = runCatching { load(path.substringBeforeLast('.') + ".jpg") }.getOrNull()
        posterBmp = bytes?.let { android.graphics.BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
    }
    Box(
        Modifier.padding(horizontal = 4.dp, vertical = 6.dp).widthIn(max = maxWidth.dp).fillMaxWidth()
            .clip(RoundedCornerShape(18.dp)).background(ClaraColors.Raised).clickable { playing = true },
        contentAlignment = Alignment.Center,
    ) {
        val p = posterBmp
        if (p != null) Image(p, "Video from Clara", contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth())
        else Box(Modifier.fillMaxWidth().height(180.dp))
        Box(Modifier.size(58.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.55f)).border(2.dp, Color.White.copy(alpha = 0.8f), CircleShape),
            contentAlignment = Alignment.Center) { Text("▶", color = Color.White, style = MaterialTheme.typography.titleLarge) }
        Text("🎬 " + path.substringAfterLast('/').replace(Regex("^\\d{8}-\\d{6}-"), "").substringBeforeLast('.'),
            style = MaterialTheme.typography.labelMedium, color = Color.White, maxLines = 1,
            modifier = Modifier.align(Alignment.BottomStart).fillMaxWidth().background(Color.Black.copy(alpha = 0.45f)).padding(horizontal = 12.dp, vertical = 6.dp))
    }
    if (playing) VideoPlayerDialog(path, load) { playing = false }
}

/** Full-screen player: downloads the video from the PC once (it's in Clara's workspace), then plays it with controls. */
@Composable
fun VideoPlayerDialog(path: String, load: suspend (String) -> ByteArray?, onClose: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    var file by remember(path) { mutableStateOf<java.io.File?>(null) }
    var failed by remember(path) { mutableStateOf(false) }
    LaunchedEffect(path) {
        val cached = java.io.File(context.cacheDir, "video-" + path.hashCode() + "." + path.substringAfterLast('.'))
        if (cached.length() > 0) { file = cached; return@LaunchedEffect }
        val bytes = runCatching { load(path) }.getOrNull()
        if (bytes == null) failed = true
        else file = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { cached.apply { writeBytes(bytes) } }
    }
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose, properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.fillMaxSize().background(Color.Black), contentAlignment = Alignment.Center) {
            val f = file
            when {
                f != null -> androidx.compose.ui.viewinterop.AndroidView(
                    factory = { ctx ->
                        android.widget.VideoView(ctx).apply {
                            val controls = android.widget.MediaController(ctx)
                            controls.setAnchorView(this)
                            setMediaController(controls)
                            setVideoPath(f.absolutePath)
                            setOnPreparedListener { mp -> mp.isLooping = false; start(); controls.show(2500) }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                failed -> Text("Couldn't load the video.", color = ClaraColors.Muted)
                else -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    TypingDots()
                    Spacer(Modifier.height(10.dp))
                    Text("Loading video…", color = ClaraColors.Muted, style = MaterialTheme.typography.labelMedium)
                }
            }
            Box(Modifier.align(Alignment.TopEnd).padding(16.dp).size(40.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.15f)).clickable(onClick = onClose),
                contentAlignment = Alignment.Center) { Text("✕", color = Color.White) }
            file?.let { f ->
                Text("Share", color = Color.White, style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 36.dp).clip(RoundedCornerShape(22.dp))
                        .background(ClaraBrush.bubble).clickable { shareVideo(context, f, path) }.padding(horizontal = 28.dp, vertical = 12.dp))
            }
        }
    }
}

/** Android's share sheet: post to TikTok / Instagram / YouTube, send it, or save it to Photos. */
private fun shareVideo(context: android.content.Context, file: java.io.File, path: String) {
    val nice = java.io.File(context.cacheDir, path.substringAfterLast('/').replace(Regex("^\\d{8}-\\d{6}-"), ""))
    if (!nice.exists() || nice.length() != file.length()) file.copyTo(nice, overwrite = true)
    val uri = androidx.core.content.FileProvider.getUriForFile(context, context.packageName + ".files", nice)
    val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
        type = "video/mp4"
        putExtra(android.content.Intent.EXTRA_STREAM, uri)
        addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(android.content.Intent.createChooser(send, "Share video").addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
}
