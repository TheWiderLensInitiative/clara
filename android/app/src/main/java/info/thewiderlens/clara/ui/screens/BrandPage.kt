package info.thewiderlens.clara.ui.screens

import info.thewiderlens.clara.data.readBounded

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import info.thewiderlens.clara.data.BrandKit
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.theme.ClaraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val PALETTES = listOf(       // primary to accent
    "#C2410C" to "#FDE047", "#2F6BFF" to "#FFD23F", "#0F766E" to "#FDBA74", "#7C3AED" to "#F0ABFC",
    "#111827" to "#22D3EE", "#BE123C" to "#FDE68A", "#15803D" to "#FEF08A", "#1E3A8A" to "#F472B6",
)

private fun parse(hex: String, fallback: Color = Color.Gray): Color =
    runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrDefault(fallback)

/** The look of the user's ads and social videos: Clara uses it for watermarks, captions and the end card. */
@Composable
fun BrandPage(
    state: UiState, onRefresh: () -> Unit, onSave: (BrandKit) -> Unit, onLogo: (ByteArray) -> Unit, onRemoveLogo: () -> Unit,
    load: suspend (String) -> ByteArray?, onBack: () -> Unit,
) {
    LaunchedEffect(Unit) { onRefresh() }
    val saved = state.brand
    var b by remember(saved) { mutableStateOf(saved) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var logo by remember { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(saved.logo, state.brandLogoVersion) {
        logo = if (saved.logo.isBlank()) null else load(saved.logo)?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        scope.launch {
            val bytes = withContext(Dispatchers.IO) { runCatching { context.contentResolver.openInputStream(uri)!!.use { it.readBounded() } }.getOrNull() }
            if (bytes != null) onLogo(bytes)
        }
    }
    val dirty = b != saved

    PageScaffold("Brand kit", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("When you ask Clara for an ad or a social video for your business, she uses this: your logo in the corner, " +
                "captions in your colors, and an end card with your call to action. You can also just tell her about your business in chat.",
                style = MaterialTheme.typography.bodyMedium, color = ClaraColors.Muted)

            EndCardPreview(b, logo)

            Section("Logo") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(64.dp).clip(RoundedCornerShape(14.dp)).background(ClaraColors.Raised), contentAlignment = Alignment.Center) {
                        logo?.let { Image(it, "Logo", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().padding(6.dp)) }
                            ?: Text("None", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
                    }
                    Spacer(Modifier.width(12.dp))
                    TextButton(onClick = { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }) {
                        Text(if (logo == null) "Choose logo" else "Change", color = ClaraColors.Cyan)
                    }
                    if (logo != null) TextButton(onClick = onRemoveLogo) { Text("Remove", color = ClaraColors.Muted) }
                }
                Text("A PNG with a transparent background looks best.", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
            }

            Section("Business") {
                Field("Name", b.name, "e.g. Sunny Bakery") { b = b.copy(name = it) }
                Field("Tagline", b.tagline, "e.g. Baked fresh every morning") { b = b.copy(tagline = it) }
                Field("Call to action", b.cta, "e.g. Order today") { b = b.copy(cta = it) }
                Field("Website or handle", b.website, "e.g. sunnybakery.com or @sunnybakery") { b = b.copy(website = it) }
            }

            Section("Colors") {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PALETTES.forEach { (p, a) ->
                        val on = b.primary.equals(p, true) && b.accent.equals(a, true)
                        Box(
                            Modifier.size(44.dp).clip(CircleShape)
                                .background(Brush.linearGradient(listOf(parse(p), parse(p), parse(a))))
                                .border(if (on) 3.dp else 1.dp, if (on) Color.White else ClaraColors.Line, CircleShape)
                                .clickable { b = b.copy(primary = p, accent = a) },
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    HexField("Main", b.primary, Modifier.weight(1f)) { b = b.copy(primary = it) }
                    HexField("Highlight", b.accent, Modifier.weight(1f)) { b = b.copy(accent = it) }
                }
            }

            Section("Font") {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    b.fonts.forEach { f ->
                        val on = f == b.font
                        Text(f, style = MaterialTheme.typography.bodyMedium, color = if (on) Color.White else ClaraColors.Text,
                            modifier = Modifier.clip(RoundedCornerShape(14.dp))
                                .then(if (on) Modifier.background(parse(b.primary, ClaraColors.Violet)) else Modifier.border(1.dp, ClaraColors.Line, RoundedCornerShape(14.dp)))
                                .clickable { b = b.copy(font = f) }.padding(horizontal = 14.dp, vertical = 8.dp))
                    }
                }
            }

            Section("Music style") {
                Field("", b.music, "e.g. warm upbeat acoustic") { b = b.copy(music = it) }
                Text("Clara composes a fresh 30-second track for each ad in this style (about 4¢).", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Muted)
            }

            GradientButton(if (dirty) "Save brand kit" else "Saved", enabled = dirty, modifier = Modifier.fillMaxWidth()) { onSave(b) }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun EndCardPreview(b: BrandKit, logo: ImageBitmap?) {
    val p = parse(b.primary, ClaraColors.Blue)
    Column(
        Modifier.fillMaxWidth().aspectRatio(16f / 10f).clip(RoundedCornerShape(18.dp))
            .background(Brush.verticalGradient(listOf(p.copy(red = p.red * 0.35f, green = p.green * 0.35f, blue = p.blue * 0.35f), p)))
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        if (logo != null) Image(logo, null, contentScale = ContentScale.Fit, modifier = Modifier.heightIn(max = 64.dp))
        else if (b.name.isNotBlank()) Text(b.name, color = parse(b.text, Color.White), fontSize = 26.sp, fontWeight = FontWeight.Black, textAlign = TextAlign.Center)
        if (b.tagline.isNotBlank()) Text(b.tagline, color = parse(b.text, Color.White), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 6.dp))
        if (b.cta.isNotBlank()) Text(b.cta.uppercase(), color = Color(0xFF111111), fontWeight = FontWeight.Black,
            modifier = Modifier.padding(top = 10.dp).clip(RoundedCornerShape(50)).background(parse(b.accent, Color.Yellow)).padding(horizontal = 18.dp, vertical = 8.dp))
        if (b.website.isNotBlank()) Text(b.website, color = parse(b.text, Color.White), style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 8.dp))
        if (logo == null && b.name.isBlank() && b.cta.isBlank()) Text("Your end card preview", color = Color.White.copy(alpha = 0.7f))
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, RoundedCornerShape(18.dp)).padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan)
        Spacer(Modifier.height(8.dp))
        content()
    }
}

@Composable
private fun Field(label: String, value: String, hint: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, { onChange(it.take(120)) }, singleLine = true, label = if (label.isNotBlank()) ({ Text(label) }) else null,
        placeholder = { Text(hint) }, modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp), shape = RoundedCornerShape(14.dp))
}

@Composable
private fun HexField(label: String, value: String, modifier: Modifier, onChange: (String) -> Unit) {
    var text by remember(value) { mutableStateOf(value) }
    OutlinedTextField(text, { t ->
        text = t.take(7)
        if (Regex("#[0-9a-fA-F]{6}").matches(text)) onChange(text.uppercase())
    }, singleLine = true, label = { Text(label) }, modifier = modifier, shape = RoundedCornerShape(14.dp),
        leadingIcon = { Box(Modifier.size(18.dp).clip(CircleShape).background(parse(value))) })
}
