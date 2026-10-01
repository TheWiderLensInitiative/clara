package dev.clara.app.ui.components

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * How Clara looks. Lives on the PC (Bridge setting "character_style"), so Clara can restyle herself and the app
 * updates instantly, no reinstall. Every field has a default = her original look.
 */
@Serializable
data class CharacterStyle(
    val body: List<String> = listOf("#58DBFB", "#2F6BFF", "#5B3CF5", "#D53CD1"),   // gradient, top-left to bottom-right
    val shape: String = "round",            // round | tall | wide | blob | square
    val hair: String = "curl",              // curl (the logo) | tuft | antenna | spikes | bun | none
    @SerialName("hair_colors") val hairColors: List<String> = listOf("#58DBFB", "#D53CD1"),
    val eyes: String = "round",             // round | big | sparkle | sleepy | dots
    @SerialName("eye_color") val eyeColor: String = "#0B0B1C",
    val cheeks: String? = "#D53CD1",        // null = no blush
    val halo: List<String> = listOf("#5B3CF5", "#D53CD1"),
    @SerialName("headphone_accents") val headphoneAccents: List<String> = listOf("#58DBFB", "#D53CD1"),
    val accessories: List<String> = emptyList(),   // glasses | sunglasses | bow | cat_ears | bunny_ears | crown | beanie | flower | scarf
    @SerialName("accessory_color") val accessoryColor: String = "#D53CD1",
    val name: String = "Original",
) {
    fun bodyColors() = body.mapNotNull(::hex).ifEmpty { listOf(ClaraCyan, ClaraMagenta) }.let { if (it.size == 1) it + it else it }
    fun hairBrush() = hairColors.mapNotNull(::hex).ifEmpty { listOf(ClaraCyan, ClaraMagenta) }.let { if (it.size == 1) it + it else it }
    fun eye() = hex(eyeColor) ?: Color(0xFF0B0B1C)
    fun cheek() = cheeks?.let(::hex)
    fun haloColors() = halo.mapNotNull(::hex).ifEmpty { listOf(Color(0xFF5B3CF5), ClaraMagenta) }
    fun phoneAccents() = headphoneAccents.mapNotNull(::hex).let { if (it.size >= 2) it else listOf(ClaraCyan, ClaraMagenta) }
    fun accessory() = hex(accessoryColor) ?: ClaraMagenta
    fun has(a: String) = a in accessories
}

private val ClaraCyan = Color(0xFF58DBFB)
private val ClaraMagenta = Color(0xFFD53CD1)

fun hex(s: String?): Color? {
    val h = s?.trim()?.removePrefix("#") ?: return null
    if (!Regex("[0-9a-fA-F]{6}").matches(h)) return null
    return Color(0xFF000000 or h.toLong(16))
}

/** The style every ClaraCharacter on screen uses (provided once at the top of the app). */
val LocalCharacterStyle = compositionLocalOf { CharacterStyle() }
