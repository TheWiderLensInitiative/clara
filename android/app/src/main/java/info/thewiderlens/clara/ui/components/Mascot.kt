package info.thewiderlens.clara.ui.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.R
import info.thewiderlens.clara.ui.theme.ClaraColors

/**
 * Clara's glowing C. It breathes slowly when idle; while she is working it breathes faster
 * and a gradient halo orbits it.
 */
@Composable
fun Mascot(size: Dp, working: Boolean = false, modifier: Modifier = Modifier) {
    val t = rememberInfiniteTransition(label = "mascot")
    val breath by t.animateFloat(
        initialValue = 0.94f, targetValue = 1.04f,
        animationSpec = infiniteRepeatable(tween(if (working) 700 else 2600, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "breath",
    )
    val glow by t.animateFloat(
        initialValue = 0.25f, targetValue = if (working) 0.85f else 0.5f,
        animationSpec = infiniteRepeatable(tween(if (working) 700 else 2600), RepeatMode.Reverse),
        label = "glow",
    )
    val spin by t.animateFloat(0f, 360f, infiniteRepeatable(tween(1600, easing = LinearEasing)), label = "spin")

    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize().alpha(glow)) {
            drawCircle(
                Brush.radialGradient(
                    listOf(ClaraColors.Violet.copy(alpha = 0.55f), ClaraColors.Magenta.copy(alpha = 0.18f), ClaraColors.Black.copy(alpha = 0f)),
                    radius = this.size.minDimension / 1.6f,
                ),
            )
        }
        if (working) {
            Canvas(Modifier.fillMaxSize().rotate(spin)) {
                drawArc(
                    Brush.sweepGradient(listOf(ClaraColors.Cyan.copy(alpha = 0f), ClaraColors.Cyan, ClaraColors.Magenta, ClaraColors.Magenta.copy(alpha = 0f))),
                    startAngle = 0f, sweepAngle = 300f, useCenter = false,
                    style = Stroke(width = this.size.minDimension * 0.035f),
                )
            }
        }
        Image(
            painter = painterResource(R.drawable.clara_mark),
            contentDescription = "Clara",
            modifier = Modifier.size(size * 0.78f).scale(breath),
        )
    }
}
