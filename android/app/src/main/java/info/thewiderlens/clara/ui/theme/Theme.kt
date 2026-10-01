package info.thewiderlens.clara.ui.theme

import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Sampled from the Clara logo.
object ClaraColors {
    val Black = Color(0xFF000000)
    val Panel = Color(0xFF0B0B14)
    val Raised = Color(0xFF14142A)
    val Line = Color(0xFF24244A)
    val Cyan = Color(0xFF58DBFB)
    val Blue = Color(0xFF2F6BFF)
    val DeepBlue = Color(0xFF0A58E0)
    val Violet = Color(0xFF5B3CF5)
    val Indigo = Color(0xFF2B18A8)
    val Magenta = Color(0xFFD53CD1)
    val Text = Color(0xFFEDEBFF)
    val Muted = Color(0xFF9C9AC0)
    val Danger = Color(0xFFFF5C7A)
    val Ok = Color(0xFF4BE3A4)
}

object ClaraBrush {
    val ribbon = Brush.linearGradient(listOf(ClaraColors.Cyan, ClaraColors.Blue, ClaraColors.Violet, ClaraColors.Magenta))
    val bubble = Brush.linearGradient(listOf(ClaraColors.DeepBlue, ClaraColors.Violet, ClaraColors.Magenta))
    val approval = Brush.linearGradient(listOf(ClaraColors.Magenta.copy(alpha = 0.9f), ClaraColors.Violet.copy(alpha = 0.9f)))
}

private val scheme = darkColorScheme(
    primary = ClaraColors.Violet,
    onPrimary = Color.White,
    secondary = ClaraColors.Cyan,
    onSecondary = ClaraColors.Black,
    tertiary = ClaraColors.Magenta,
    background = ClaraColors.Black,
    onBackground = ClaraColors.Text,
    surface = ClaraColors.Panel,
    onSurface = ClaraColors.Text,
    surfaceVariant = ClaraColors.Raised,
    onSurfaceVariant = ClaraColors.Muted,
    surfaceContainer = ClaraColors.Panel,
    surfaceContainerHigh = ClaraColors.Raised,
    outline = ClaraColors.Line,
    error = ClaraColors.Danger,
)

private val type = Typography(
    headlineMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
    titleMedium = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.4.sp),
)

@Composable
fun ClaraTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = scheme, typography = type) {
    // Every Text defaults to Clara's light text color, even outside a Surface.
    CompositionLocalProvider(LocalContentColor provides ClaraColors.Text, content = content)
}
