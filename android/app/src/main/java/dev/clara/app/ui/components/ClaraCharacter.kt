package dev.clara.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp
import dev.clara.app.ui.theme.ClaraColors
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

/** What Clara is doing right now; drives the character's pose and props. */
enum class Mood { Idle, Thinking, Talking, Working, Browsing, Searching, Scheduling, Waiting, Done, Sleeping }

private val AT_LAPTOP = setOf(Mood.Working, Mood.Browsing, Mood.Searching, Mood.Scheduling)
private val HEADPHONES = AT_LAPTOP + Mood.Thinking

private val Dark = Color(0xFF15152E)
private val Darker = Color(0xFF0B0B1C)

/**
 * Clara's animated character, drawn procedurally on a 200x200 grid so it is crisp at any size.
 * A glowing gradient creature (the logo's colors) with a C-shaped curl of hair.
 */
@Composable
fun ClaraCharacter(mood: Mood, size: Dp, modifier: Modifier = Modifier, style: CharacterStyle = LocalCharacterStyle.current) {
    val time by produceState(0f) {
        val start = withFrameNanos { it }
        while (true) withFrameNanos { value = (it - start) / 1_000_000_000f }
    }
    val laptop by animateFloatAsState(if (mood in AT_LAPTOP) 1f else 0f, tween(500), label = "laptop")
    val phones by animateFloatAsState(if (mood in HEADPHONES) 1f else 0f, tween(450), label = "phones")
    val sleep by animateFloatAsState(if (mood == Mood.Sleeping) 1f else 0f, tween(700), label = "sleep")
    val hand by animateFloatAsState(if (mood == Mood.Waiting) 1f else 0f, tween(350), label = "hand")
    val measurer = rememberTextMeasurer()

    Canvas(modifier.size(size)) {
        val u = this.size.minDimension / 200f
        scale(u, u, pivot = Offset.Zero) {
            val bob = when (mood) {
                Mood.Done -> -abs(sin(time * 7f)) * 9f
                Mood.Working, Mood.Browsing, Mood.Searching, Mood.Scheduling -> sin(time * 10f) * 1.2f
                Mood.Talking -> sin(time * 3f) * 1.5f
                Mood.Sleeping -> sin(time * 0.9f) * 2.5f
                else -> sin(time * 1.6f) * 2.2f
            }
            val breathe = 1f + sin(time * (if (mood == Mood.Sleeping) 0.9f else 1.6f)) * 0.018f
            val working = mood in AT_LAPTOP

            // halo
            val pulse = if (working || mood == Mood.Waiting) 0.45f + 0.15f * sin(time * 4f) else 0.32f
            val halo = style.haloColors()
            drawCircle(
                Brush.radialGradient(
                    listOf(halo.first().copy(alpha = pulse * (1 - sleep * 0.6f)), halo.last().copy(alpha = 0.12f), Color.Transparent),
                    center = Offset(100f, 100f), radius = 98f,
                ),
                radius = 98f, center = Offset(100f, 100f),
            )

            translate(top = bob) {
                val top = bodyTop(style, breathe)
                earsBehind(style, top, time, sleep)
                headphonesBand(phones)
                body(breathe, sleep, style)
                if (!style.has("beanie") && !style.has("crown")) hair(style, top, time, sleep)
                face(mood, time, sleep, laptop, style)
                accessoriesFront(style, top, time, phones)
                headphonesCups(phones, time, working, style)
                if (hand > 0.01f) raisedHand(hand, time, style)
            }
            if (laptop > 0.01f) laptopAndHands(laptop, time, mood, style)
            props(mood, time, measurer, sleep)
        }
    }
}

// --- body -----------------------------------------------------------------------------
private fun dims(style: CharacterStyle): Pair<Float, Float> = when (style.shape) {
    "tall" -> 94f to 116f
    "wide" -> 126f to 90f
    "square" -> 106f to 100f
    "blob" -> 112f to 98f
    else -> 108f to 100f
}

private fun bodyTop(style: CharacterStyle, breathe: Float) = 98f - dims(style).second / breathe / 2

private fun DrawScope.body(breathe: Float, sleep: Float, style: CharacterStyle) {
    val (bw, bh) = dims(style)
    val w = bw * breathe
    val h = bh / breathe
    val topLeft = Offset(100f - w / 2, 98f - h / 2)
    val brush = Brush.linearGradient(style.bodyColors(), start = Offset(55f, 45f), end = Offset(150f, 150f))
    val alpha = 1f - sleep * 0.35f
    when (style.shape) {
        "square" -> drawRoundRect(brush, topLeft = topLeft, size = Size(w, h), cornerRadius = CornerRadius(30f), alpha = alpha)
        "blob" -> {
            // a soft, slightly lumpy droplet
            val p = Path().apply {
                moveTo(100f, topLeft.y)
                cubicTo(100f + w * 0.42f, topLeft.y + 2f, 100f + w * 0.55f, topLeft.y + h * 0.62f, 100f + w * 0.40f, topLeft.y + h * 0.9f)
                cubicTo(100f + w * 0.2f, topLeft.y + h * 1.04f, 100f - w * 0.25f, topLeft.y + h * 1.04f, 100f - w * 0.42f, topLeft.y + h * 0.86f)
                cubicTo(100f - w * 0.56f, topLeft.y + h * 0.6f, 100f - w * 0.44f, topLeft.y + 4f, 100f, topLeft.y)
                close()
            }
            drawPath(p, brush, alpha = alpha)
        }
        else -> drawOval(brush, topLeft = topLeft, size = Size(w, h), alpha = alpha)
    }
    // soft top-left highlight, like the logo's sheen
    drawOval(Color.White.copy(alpha = 0.22f), topLeft = Offset(64f, 56f), size = Size(34f, 18f))
    // inner fold, echoing the ribbon in the logo
    drawArc(
        Color.White.copy(alpha = 0.10f), startAngle = 110f, sweepAngle = 120f, useCenter = false,
        topLeft = Offset(58f, 58f), size = Size(84f, 84f), style = Stroke(width = 6f, cap = StrokeCap.Round),
    )
}

private fun DrawScope.hair(style: CharacterStyle, top: Float, time: Float, sleep: Float) {
    val dy = top - 48f   // the original curl sits on a head whose top is at y=48
    val colors = style.hairBrush()
    val sway = sin(time * 2.2f) * 6f * (1 - sleep)
    translate(top = dy) {
        when (style.hair) {
            "none" -> {}
            "tuft" -> rotate(sway, pivot = Offset(100f, 50f)) {
                for ((k, ang) in listOf(-22f, 0f, 22f).withIndex())
                    rotate(ang, pivot = Offset(100f, 50f)) {
                        drawLine(Brush.linearGradient(colors, start = Offset(100f, 50f), end = Offset(100f, 30f)), Offset(100f, 50f),
                            Offset(100f, 32f - (if (k == 1) 6f else 0f)), strokeWidth = 5.5f, cap = StrokeCap.Round)
                    }
            }
            "antenna" -> rotate(sway * 1.4f, pivot = Offset(100f, 50f)) {
                drawLine(colors.first(), Offset(100f, 50f), Offset(100f, 24f), strokeWidth = 3.5f, cap = StrokeCap.Round)
                drawCircle(colors.last(), radius = 6.5f + sin(time * 4f), center = Offset(100f, 21f))
                drawCircle(Color.White.copy(alpha = 0.5f), radius = 2f, center = Offset(98f, 19f))
            }
            "spikes" -> {
                val p = Path().apply {
                    moveTo(70f, 56f); lineTo(76f, 30f); lineTo(88f, 48f); lineTo(100f, 22f); lineTo(112f, 48f); lineTo(124f, 30f); lineTo(130f, 56f); close()
                }
                drawPath(p, Brush.linearGradient(colors, start = Offset(70f, 22f), end = Offset(130f, 56f)))
            }
            "bun" -> {
                drawCircle(Brush.linearGradient(colors, start = Offset(88f, 20f), end = Offset(112f, 46f)), radius = 13f, center = Offset(100f, 36f))
                drawCircle(Color.White.copy(alpha = 0.2f), radius = 4f, center = Offset(95f, 31f))
            }
            else -> rotate(sway, pivot = Offset(100f, 50f)) {   // "curl": the C of the logo, worn as a cowlick
                drawArc(
                    Brush.linearGradient(colors, start = Offset(88f, 26f), end = Offset(114f, 52f)),
                    startAngle = 40f, sweepAngle = 280f, useCenter = false,
                    topLeft = Offset(89f, 28f), size = Size(22f, 22f), style = Stroke(width = 6.5f, cap = StrokeCap.Round),
                )
            }
        }
    }
}

// --- accessories ----------------------------------------------------------------------------
private fun DrawScope.earsBehind(style: CharacterStyle, top: Float, time: Float, sleep: Float) {
    val c = style.bodyColors()
    if (style.has("cat_ears")) for (side in listOf(-1f, 1f)) {
        val p = Path().apply {
            moveTo(100f + side * 20f, top + 14f); lineTo(100f + side * 40f, top - 16f); lineTo(100f + side * 50f, top + 22f); close()
        }
        drawPath(p, if (side < 0) c.first() else c.last())
        val inner = Path().apply {
            moveTo(100f + side * 27f, top + 14f); lineTo(100f + side * 39f, top - 6f); lineTo(100f + side * 45f, top + 18f); close()
        }
        drawPath(inner, style.accessory().copy(alpha = 0.8f))
    }
    if (style.has("bunny_ears")) for (side in listOf(-1f, 1f)) {
        val droop = sin(time * 1.5f + side) * 4f + sleep * 18f
        rotate(side * (14f + droop), pivot = Offset(100f + side * 22f, top + 12f)) {
            drawRoundRect(if (side < 0) c.first() else c.last(), topLeft = Offset(100f + side * 22f - 10f, top - 44f), size = Size(20f, 60f), cornerRadius = CornerRadius(10f))
            drawRoundRect(style.accessory().copy(alpha = 0.7f), topLeft = Offset(100f + side * 22f - 5f, top - 36f), size = Size(10f, 44f), cornerRadius = CornerRadius(5f))
        }
    }
}

private fun DrawScope.accessoriesFront(style: CharacterStyle, top: Float, time: Float, phones: Float) {
    val acc = style.accessory()
    if (style.has("glasses") || style.has("sunglasses")) {
        val dark = style.has("sunglasses")
        for (x in listOf(82f, 118f)) {
            if (dark) drawRoundRect(Color(0xFF0B0B1C).copy(alpha = 0.92f), topLeft = Offset(x - 13f, 80f), size = Size(26f, 20f), cornerRadius = CornerRadius(8f))
            drawRoundRect(acc, topLeft = Offset(x - 13f, 80f), size = Size(26f, 20f), cornerRadius = CornerRadius(8f), style = Stroke(3f))
            if (dark) drawLine(Color.White.copy(alpha = 0.45f), Offset(x - 8f, 84f), Offset(x - 2f, 84f), strokeWidth = 2f, cap = StrokeCap.Round)
        }
        drawLine(acc, Offset(95f, 88f), Offset(105f, 88f), strokeWidth = 3f, cap = StrokeCap.Round)
    }
    if (style.has("crown")) {
        val p = Path().apply {
            moveTo(80f, top + 6f); lineTo(80f, top - 16f); lineTo(90f, top - 6f); lineTo(100f, top - 22f); lineTo(110f, top - 6f)
            lineTo(120f, top - 16f); lineTo(120f, top + 6f); close()
        }
        drawPath(p, Brush.linearGradient(listOf(Color(0xFFFFE27A), Color(0xFFF5B301)), start = Offset(80f, top - 22f), end = Offset(120f, top + 6f)))
        for ((k, x) in listOf(80f, 100f, 120f).withIndex()) drawCircle(if (k == 1) acc else Color.White, 2.8f, Offset(x, if (k == 1) top - 22f else top - 16f))
    }
    if (style.has("beanie")) {
        drawArc(acc, 180f, 180f, true, topLeft = Offset(64f, top - 6f), size = Size(72f, 44f))
        drawRoundRect(acc.copy(alpha = 1f), topLeft = Offset(62f, top + 12f), size = Size(76f, 11f), cornerRadius = CornerRadius(5.5f))
        drawRoundRect(Color.White.copy(alpha = 0.22f), topLeft = Offset(62f, top + 12f), size = Size(76f, 11f), cornerRadius = CornerRadius(5.5f))
        drawCircle(Color.White.copy(alpha = 0.9f), 7f, Offset(100f, top - 8f))
    }
    if (style.has("bow")) {
        val c = Offset(70f, top + 18f)
        rotate(-18f, pivot = c) {
            for (side in listOf(-1f, 1f)) {
                val p = Path().apply { moveTo(c.x, c.y); lineTo(c.x + side * 15f, c.y - 10f); lineTo(c.x + side * 15f, c.y + 10f); close() }
                drawPath(p, acc)
            }
            drawCircle(acc, 4.5f, c); drawCircle(Color.White.copy(alpha = 0.35f), 2f, c + Offset(-1f, -1f))
        }
    }
    if (style.has("flower")) {
        val c = Offset(134f, top + 20f)
        for (k in 0 until 5) {
            val ang = k * 72f * PI.toFloat() / 180f + time * 0.3f
            drawCircle(acc, 5.5f, Offset(c.x + 6.5f * kotlin.math.cos(ang), c.y + 6.5f * sin(ang)))
        }
        drawCircle(Color(0xFFFFE27A), 4.2f, c)
    }
    if (style.has("scarf")) {
        drawRoundRect(acc, topLeft = Offset(60f, 132f), size = Size(80f, 13f), cornerRadius = CornerRadius(6.5f))
        rotate(8f + sin(time * 2f) * 4f, pivot = Offset(124f, 140f)) {
            drawRoundRect(acc, topLeft = Offset(118f, 138f), size = Size(12f, 30f), cornerRadius = CornerRadius(5f))
        }
        for (x in listOf(72f, 88f, 104f)) drawLine(Color.White.copy(alpha = 0.25f), Offset(x, 133f), Offset(x + 6f, 144f), strokeWidth = 2.5f)
    }
}

// --- face -----------------------------------------------------------------------------
private fun DrawScope.face(mood: Mood, time: Float, sleep: Float, laptop: Float, style: CharacterStyle) {
    val Darker = style.eye()
    val blinking = (time % 3.7f) < 0.13f && mood != Mood.Done
    val look = when (mood) {
        Mood.Working, Mood.Scheduling -> Offset(sin(time * 5f) * 0.25f, 0.85f)
        Mood.Browsing, Mood.Searching -> Offset(sin(time * 1.8f) * 0.8f, 0.7f)
        Mood.Thinking -> Offset(0.6f, -0.85f)
        Mood.Waiting -> Offset(0f, 0.05f)
        Mood.Talking -> Offset(0f, 0.1f)
        else -> Offset(sin(time * 0.5f) * 0.6f, sin(time * 0.37f) * 0.3f)
    }
    val eyeY = 90f + laptop * 2f
    for (x in listOf(82f, 118f)) {
        if (sleep > 0.5f || blinking) {
            drawArc(Darker, 20f, 140f, false, topLeft = Offset(x - 8f, eyeY - 6f), size = Size(16f, 10f), style = Stroke(3.2f, cap = StrokeCap.Round))
        } else if (mood == Mood.Done) {
            // happy ^ ^ eyes
            drawArc(Darker, 200f, 140f, false, topLeft = Offset(x - 8f, eyeY - 3f), size = Size(16f, 14f), style = Stroke(3.4f, cap = StrokeCap.Round))
        } else when (style.eyes) {
            "dots" -> drawCircle(Darker, radius = 4.6f, center = Offset(x + look.x * 2.5f, eyeY + look.y * 3f))
            "sleepy" -> {
                drawArc(Darker, 200f, 140f, false, topLeft = Offset(x - 8f, eyeY - 4f), size = Size(16f, 12f), style = Stroke(3.2f, cap = StrokeCap.Round))
                drawCircle(Darker, radius = 3.4f, center = Offset(x + look.x * 2f, eyeY + 3f))
            }
            else -> {
                val big = style.eyes == "big" || style.eyes == "sparkle"
                val ew = if (big) 19f else 16f; val eh = if (big) 23f else 20f
                drawOval(Color.White, topLeft = Offset(x - ew / 2, eyeY - eh / 2), size = Size(ew, eh))
                val p = Offset(x + look.x * 3.2f, eyeY + look.y * 4f)
                drawCircle(Darker, radius = if (big) 7f else 5.6f, center = p)
                drawCircle(Color.White, radius = if (big) 2.4f else 1.8f, center = p + Offset(-1.8f, -2f))
                if (style.eyes == "sparkle") drawCircle(Color.White, radius = 1.3f, center = p + Offset(2.4f, 2.2f))
            }
        }
    }
    if (mood == Mood.Waiting) {
        // raised brows: curious
        for (x in listOf(82f, 118f)) drawLine(Darker, Offset(x - 7f, eyeY - 17f), Offset(x + 6f, eyeY - 19f), strokeWidth = 3f, cap = StrokeCap.Round)
    }
    // cheeks
    style.cheek()?.let { c -> for (x in listOf(69f, 131f)) drawCircle(c.copy(alpha = 0.45f), radius = 6.5f, center = Offset(x, 106f)) }
    // mouth
    val m = Offset(100f, 112f)
    when {
        sleep > 0.5f -> drawOval(Darker, topLeft = m + Offset(-3f, -2f), size = Size(6f, 5f))
        mood == Mood.Talking -> {
            val open = 2f + abs(sin(time * 13f)) * 7f
            drawOval(Darker, topLeft = m + Offset(-6f, -2f), size = Size(12f, open))
        }
        mood == Mood.Waiting -> drawOval(Darker, topLeft = m + Offset(-3.5f, -2f), size = Size(7f, 8f))
        mood == Mood.Done -> drawArc(Darker, 0f, 180f, true, topLeft = m + Offset(-10f, -7f), size = Size(20f, 16f))
        mood in AT_LAPTOP -> drawLine(Darker, m + Offset(-5f, 1f), m + Offset(5f, 0f), strokeWidth = 3f, cap = StrokeCap.Round)
        else -> drawArc(Darker, 15f, 150f, false, topLeft = m + Offset(-8f, -8f), size = Size(16f, 12f), style = Stroke(3.2f, cap = StrokeCap.Round))
    }
}

// --- headphones -------------------------------------------------------------------------
private fun DrawScope.headphonesBand(on: Float) {
    if (on < 0.01f) return
    translate(top = (1 - on) * -34f) {
        drawArc(Dark.copy(alpha = on), 195f, 150f, false, topLeft = Offset(40f, 36f), size = Size(120f, 110f), style = Stroke(8f, cap = StrokeCap.Round))
        drawArc(ClaraColors.Cyan.copy(alpha = 0.6f * on), 205f, 130f, false, topLeft = Offset(43f, 38f), size = Size(114f, 106f), style = Stroke(2f, cap = StrokeCap.Round))
    }
}

private fun DrawScope.headphonesCups(on: Float, time: Float, working: Boolean, style: CharacterStyle) {
    if (on < 0.01f) return
    translate(top = (1 - on) * -34f) {
        val acc = style.phoneAccents()
        for ((x, accent) in listOf(36f to acc[0], 146f to acc[1])) {
            drawRoundRect(Dark.copy(alpha = on), topLeft = Offset(x, 78f), size = Size(18f, 32f), cornerRadius = CornerRadius(9f))
            // little equalizer glow on the cup while music plays
            val level = if (working) 0.55f + 0.45f * abs(sin(time * 6f + x)) else 0.5f
            drawRoundRect(accent.copy(alpha = level * on), topLeft = Offset(x + 6f, 86f), size = Size(6f, 16f), cornerRadius = CornerRadius(3f))
        }
    }
}

// --- waiting: raised hand ------------------------------------------------------------------
private fun DrawScope.raisedHand(p: Float, time: Float, style: CharacterStyle) {
    val handColor = style.bodyColors().last()
    val wave = sin(time * 9f) * 14f
    rotate(wave, pivot = Offset(150f, 100f)) {
        translate(left = (1 - p) * -20f, top = (1 - p) * 30f) {
            drawLine(handColor.copy(alpha = p), Offset(146f, 104f), Offset(162f, 70f), strokeWidth = 11f, cap = StrokeCap.Round)
            drawCircle(handColor.copy(alpha = p), radius = 9f, center = Offset(163f, 66f))
        }
    }
}

// --- laptop -------------------------------------------------------------------------------
private fun DrawScope.laptopAndHands(p: Float, time: Float, mood: Mood, style: CharacterStyle) {
    val bc = style.bodyColors()
    translate(top = (1 - p) * 70f) {
        // screen light spilling up onto her face
        val flicker = 0.18f + 0.07f * sin(time * 17f) + 0.05f * sin(time * 5.3f)
        drawOval(
            Brush.radialGradient(listOf(ClaraColors.Cyan.copy(alpha = flicker * p), Color.Transparent), center = Offset(100f, 118f), radius = 46f),
            topLeft = Offset(54f, 88f), size = Size(92f, 60f),
        )
        // typing hands peeking over the lid, alternating
        val speed = if (mood == Mood.Browsing) 5f else 13f
        val l = abs(sin(time * speed)) * 7f
        val r = abs(sin(time * speed + 1.7f)) * 7f
        for ((c, fill) in listOf(Offset(78f, 128f - l) to lerp(bc.first(), Color.White, 0.45f), Offset(122f, 128f - r) to lerp(bc.last(), Color.White, 0.45f))) {
            drawCircle(fill, radius = 8.5f, center = c)
            drawCircle(Darker, radius = 8.5f, center = c, style = Stroke(2f))
        }
        // lid (back of the screen faces us)
        drawRoundRect(Dark, topLeft = Offset(56f, 132f), size = Size(88f, 46f), cornerRadius = CornerRadius(7f))
        drawRoundRect(ClaraColors.Line, topLeft = Offset(56f, 132f), size = Size(88f, 46f), cornerRadius = CornerRadius(7f), style = Stroke(1.5f))
        // the C logo glowing on the lid
        drawArc(
            Brush.linearGradient(listOf(ClaraColors.Cyan, ClaraColors.Magenta), start = Offset(92f, 147f), end = Offset(108f, 163f)),
            40f, 280f, false, topLeft = Offset(92f, 147f), size = Size(16f, 16f), style = Stroke(3.2f, cap = StrokeCap.Round),
        )
        // base
        val base = Path().apply { moveTo(46f, 178f); lineTo(154f, 178f); lineTo(160f, 185f); lineTo(40f, 185f); close() }
        drawPath(base, Color(0xFF262650))
    }
}

// --- floating props -------------------------------------------------------------------------
private fun DrawScope.props(mood: Mood, time: Float, measurer: androidx.compose.ui.text.TextMeasurer, sleep: Float) {
    val glyphs = when (mood) {
        Mood.Working -> listOf("</>", "{ }", "\$_")
        Mood.Browsing -> listOf("🌐", "↗", "🌐")
        Mood.Searching -> listOf("🔍", "?", "🔍")
        Mood.Scheduling -> listOf("⏰", "🕒", "⏰")
        else -> emptyList()
    }
    glyphs.forEachIndexed { i, g ->
        val phase = (time * 0.55f + i / 3f) % 1f
        val x = if (i % 2 == 0) 8f + i * 3f else 158f
        val y = 130f - phase * 95f
        val a = (sin(phase * PI).toFloat()).coerceIn(0f, 1f)
        drawText(
            measurer, g, topLeft = Offset(x, y),
            style = TextStyle(color = (if (i % 2 == 0) ClaraColors.Cyan else ClaraColors.Magenta).copy(alpha = a), fontSize = 14.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold),
        )
    }
    when (mood) {
        Mood.Thinking -> {
            // thought bubbles rising to the upper right, dots cycling inside the big one
            drawCircle(ClaraColors.Raised, 4f, Offset(146f, 58f)); drawCircle(ClaraColors.Raised, 6.5f, Offset(156f, 44f))
            drawRoundRect(ClaraColors.Raised, topLeft = Offset(150f, 6f), size = Size(44f, 26f), cornerRadius = CornerRadius(13f))
            for (d in 0..2) {
                val on = ((time * 3f).toInt() % 3) == d
                drawCircle(if (on) ClaraColors.Cyan else ClaraColors.Muted, if (on) 3.6f else 2.8f, Offset(161f + d * 11f, 19f))
            }
        }
        Mood.Waiting -> {
            val s = 1f + 0.08f * sin(time * 5f)
            scale(s, s, pivot = Offset(40f, 38f)) {
                drawCircle(ClaraColors.Magenta, 17f, Offset(40f, 38f))
                drawText(measurer, "?", topLeft = Offset(33.5f, 24f), style = TextStyle(color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold))
            }
        }
        Mood.Done -> {
            for (k in 0..4) {
                val ang = k * 72f * PI.toFloat() / 180f + time
                val r = 82f + 6f * sin(time * 5f + k)
                val c = Offset(100f + r * kotlin.math.cos(ang), 100f + r * sin(ang))
                sparkle(c, 5f + 2.5f * abs(sin(time * 6f + k)), if (k % 2 == 0) ClaraColors.Cyan else ClaraColors.Magenta)
            }
        }
        Mood.Sleeping -> {
            for (k in 0..2) {
                val phase = (time * 0.35f + k / 3f) % 1f
                val a = sin(phase * PI).toFloat().coerceIn(0f, 1f) * sleep
                drawText(
                    measurer, "z", topLeft = Offset(140f + phase * 30f, 60f - phase * 50f),
                    style = TextStyle(color = ClaraColors.Muted.copy(alpha = a), fontSize = (11 + k * 4).sp, fontWeight = FontWeight.Bold),
                )
            }
        }
        else -> {}
    }
}

private fun DrawScope.sparkle(c: Offset, r: Float, color: Color) {
    val p = Path().apply {
        moveTo(c.x, c.y - r); quadraticTo(c.x, c.y, c.x + r, c.y); quadraticTo(c.x, c.y, c.x, c.y + r)
        quadraticTo(c.x, c.y, c.x - r, c.y); quadraticTo(c.x, c.y, c.x, c.y - r); close()
    }
    drawPath(p, color)
}
