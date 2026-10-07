package info.thewiderlens.clara.ui.screens

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.BridgeApi
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.components.ClaraCharacter
import info.thewiderlens.clara.ui.components.GradientButton
import info.thewiderlens.clara.ui.moodOf
import info.thewiderlens.clara.ui.theme.ClaraColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/**
 * Live screen: watch Clara's browser as she uses it, and take control from the phone.
 * While only watching, the Bridge drops all input, so a stray tap can never click anything.
 */
@Composable
fun LiveScreenPage(state: UiState, api: BridgeApi?, onBack: () -> Unit, startInControl: Boolean = false) {
    var frame by remember { mutableStateOf<ImageBitmap?>(null) }
    var device by remember { mutableStateOf(1280f to 720f) }
    var online by remember { mutableStateOf(false) }
    var takeover by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf("") }
    var socket by remember { mutableStateOf<WebSocket?>(null) }
    var typed by remember { mutableStateOf("") }
    var askedControl by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    DisposableEffect(api) {
        val streamJob = kotlinx.coroutines.Job(scope.coroutineContext[kotlinx.coroutines.Job])
        val streamScope = kotlinx.coroutines.CoroutineScope(scope.coroutineContext + streamJob)
        val ws = api?.let { a ->
            info.thewiderlens.clara.data.BrowserConnection(a, streamScope,
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        val m = runCatching { JSONObject(text) }.getOrNull() ?: return
                        when (m.optString("type")) {
                            "frame" -> streamScope.launch {
                                val seq = m.optLong("seq")
                                val md = m.optJSONObject("metadata")
                                val bmp = withContext(Dispatchers.Default) {
                                    runCatching {
                                        val bytes = Base64.decode(m.optString("data"), Base64.DEFAULT)
                                        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
                                    }.getOrNull()
                                }
                                if (bmp != null) {
                                    frame = bmp
                                    // The frame shows the visible viewport, which can be shorter than the reported device height
                                    // (577 vs 720 here): map taps with the frame's own shape, in page (CSS) pixels.
                                    val cssPerPx = (md?.optDouble("deviceWidth", bmp.width.toDouble()) ?: bmp.width.toDouble()).toFloat() / bmp.width
                                    device = bmp.width * cssPerPx to bmp.height * cssPerPx
                                }
                                webSocket.send("""{"type":"ack","seq":$seq}""")   // one frame in flight: never lags behind
                            }
                            "online" -> {
                                online = true; takeover = m.optBoolean("takeover")
                                if (startInControl && !takeover && !askedControl) {   // came from "Take over" on a help card or notification
                                    askedControl = true
                                    webSocket.send("""{"type":"takeover","on":true}""")
                                }
                            }
                            "offline" -> { online = false; frame = null }
                            "takeover" -> takeover = m.optBoolean("on")
                            "url" -> url = m.optString("url")
                        }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { online = false; takeover = false }
                }, onSocket = { socket = it },
            )
        }
        onDispose {
            streamJob.cancel(); ws?.close(); socket = null }
    }

    fun send(json: String) { socket?.send(json) }
    fun mouse(type: String, x: Float, y: Float, extra: String = "") =
        send("""{"type":"input_mouse","eventType":"$type","x":$x,"y":$y,"button":"left","clickCount":1$extra}""")
    fun key(key: String, code: String, vk: Int, text: String? = null) {
        val t = text?.let { ""","text":${JSONObject.quote(it)}""" } ?: ""
        send("""{"type":"input_keyboard","eventType":"keyDown","key":${JSONObject.quote(key)},"code":"$code","windowsVirtualKeyCode":$vk$t}""")
        send("""{"type":"input_keyboard","eventType":"keyUp","key":${JSONObject.quote(key)},"code":"$code","windowsVirtualKeyCode":$vk}""")
    }

    // In control: full screen, sideways, so the page is big enough to use.
    if (takeover && online && frame != null) {
        TakeoverView(frame!!, device, url, onMouse = { t, x, y, e -> mouse(t, x, y, e) }, onKey = { k, c, v, t -> key(k, c, v, t) }, onType = { text ->
            text.forEach { c -> send("""{"type":"input_keyboard","eventType":"keyDown","key":${JSONObject.quote(c.toString())},"text":${JSONObject.quote(c.toString())}}""") }
        }, onHandBack = { send("""{"type":"takeover","on":false}""") })
        return
    }

    PageScaffold("Screen", onBack) {
        Column(Modifier.fillMaxSize().imePadding().padding(horizontal = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 6.dp)) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(if (takeover) ClaraColors.Magenta else if (online) ClaraColors.Ok else ClaraColors.Muted))
                Spacer(Modifier.width(8.dp))
                Text(
                    when {
                        takeover -> "You're in control · Clara is paused"
                        online -> "Live · Clara's browser"
                        else -> "Clara's browser isn't open right now"
                    },
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted,
                )
            }
            if (url.isNotBlank() && online) {
                Text(url, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Cyan, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(6.dp))
            }

            val (dw, dh) = device
            val shot = frame
            if (shot == null || !online) {
                Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    ClaraCharacter(moodOf(state), size = 140.dp)
                    Text(
                        "When Clara opens her browser for a task, you'll see it here live — and you can take over to log in or solve a CAPTCHA for her.",
                        color = ClaraColors.Muted, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(horizontal = 16.dp),
                    )
                }
            } else {
                BoxWithConstraints(
                    Modifier.fillMaxWidth().aspectRatio(dw / dh).clip(RoundedCornerShape(14.dp))
                        .border(2.dp, if (takeover) ClaraColors.Magenta else ClaraColors.Line, RoundedCornerShape(14.dp)),
                ) {
                    val scale = constraints.maxWidth / dw
                    fun page(o: Offset) = (o.x / scale) to (o.y / scale)
                    Image(
                        shot, "Clara's browser", contentScale = ContentScale.FillBounds,
                        modifier = Modifier.fillMaxSize()
                            .pointerInput(takeover, scale) {
                                if (!takeover) return@pointerInput
                                detectTapGestures { o ->
                                    val (x, y) = page(o)
                                    mouse("mouseMoved", x, y); mouse("mousePressed", x, y); mouse("mouseReleased", x, y)
                                }
                            }
                            .pointerInput(takeover, scale) {
                                if (!takeover) return@pointerInput
                                detectVerticalDragGestures { change, dy ->
                                    val (x, y) = page(change.position)
                                    mouse("mouseWheel", x, y, ""","deltaX":0,"deltaY":${-dy / scale}""")
                                }
                            },
                    )
                }
            }

            Spacer(Modifier.height(12.dp))
            if (online) {
                if (!takeover) {
                    GradientButton("Take over", modifier = Modifier.fillMaxWidth()) { send("""{"type":"takeover","on":true}""") }
                    Text(
                        "Clara pauses while you're in control. Tap to click, swipe to scroll, type below.",
                        style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted, modifier = Modifier.padding(top = 6.dp),
                    )
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TextField(
                            typed, { typed = it }, placeholder = { Text("Type into the page…") }, singleLine = true,
                            modifier = Modifier.weight(1f).clip(RoundedCornerShape(18.dp)),
                            colors = TextFieldDefaults.colors(
                                focusedContainerColor = ClaraColors.Raised, unfocusedContainerColor = ClaraColors.Raised,
                                focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                            ),
                        )
                        Spacer(Modifier.width(6.dp))
                        OutlinedButton(onClick = {
                            typed.forEach { c -> send("""{"type":"input_keyboard","eventType":"keyDown","key":${JSONObject.quote(c.toString())},"text":${JSONObject.quote(c.toString())}}""") }
                            typed = ""
                        }, shape = RoundedCornerShape(14.dp)) { Text("Type", color = ClaraColors.Text) }
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { key("Backspace", "Backspace", 8) }, shape = RoundedCornerShape(14.dp)) { Text("⌫", color = ClaraColors.Text) }
                        OutlinedButton(onClick = { key("Tab", "Tab", 9) }, shape = RoundedCornerShape(14.dp)) { Text("Tab", color = ClaraColors.Text) }
                        OutlinedButton(onClick = { key("Enter", "Enter", 13, "\r") }, shape = RoundedCornerShape(14.dp)) { Text("Enter", color = ClaraColors.Text) }
                    }
                    Spacer(Modifier.height(10.dp))
                    GradientButton("Hand back to Clara", modifier = Modifier.fillMaxWidth()) { send("""{"type":"takeover","on":false}""") }
                }
            }
        }
    }
}


/** Full-screen control of Clara's browser: sideways, pinch to zoom, one finger scrolls the page, tap to click. */
@Composable
private fun TakeoverView(
    frame: ImageBitmap, device: Pair<Float, Float>, url: String,
    onMouse: (String, Float, Float, String) -> Unit, onKey: (String, String, Int, String?) -> Unit,
    onType: (String) -> Unit, onHandBack: () -> Unit,
) {
    val activity = androidx.activity.compose.LocalActivity.current
    // Clara switches her page to phone size while you're in control (mobile layout, big buttons): then stay upright.
    // A desktop-shaped page still turns the phone sideways so it's as big as possible.
    val tall = device.second > device.first
    DisposableEffect(tall) {
        val before = activity?.requestedOrientation
        activity?.requestedOrientation = if (tall) android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                                         else android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        onDispose { activity?.requestedOrientation = before ?: android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED }
    }
    androidx.activity.compose.BackHandler { onHandBack() }   // Back = done: hand control back
    var zoom by remember { mutableStateOf(1f) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    var keyboard by remember { mutableStateOf(false) }
    var typed by remember { mutableStateOf("") }
    val (dw, dh) = device
    Column(Modifier.fillMaxSize().background(Color.Black).systemBarsPadding().imePadding()) {
        // slim control bar
        Row(Modifier.fillMaxWidth().background(ClaraColors.Panel).padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(ClaraColors.Magenta))
            Spacer(Modifier.width(6.dp))
            Text(url.removePrefix("https://").removePrefix("www.").ifBlank { "You're in control" }, style = MaterialTheme.typography.labelMedium,
                color = ClaraColors.Muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            androidx.compose.material3.TextButton(onClick = { keyboard = !keyboard }) { Text(if (keyboard) "Hide keyboard" else "⌨ Type", color = ClaraColors.Text) }
            androidx.compose.material3.TextButton(onClick = { onKey("Backspace", "Backspace", 8, null) }) { Text("⌫", color = ClaraColors.Text) }
            androidx.compose.material3.TextButton(onClick = { onKey("Enter", "Enter", 13, "\r") }) { Text("Enter", color = ClaraColors.Text) }
            if (zoom > 1.01f) androidx.compose.material3.TextButton(onClick = { zoom = 1f; pan = Offset.Zero }) { Text("Fit", color = ClaraColors.Cyan) }
            GradientButton("Hand back", modifier = Modifier.padding(start = 4.dp).width(130.dp)) { onHandBack() }
        }
        if (keyboard) {
            Row(Modifier.fillMaxWidth().padding(6.dp), verticalAlignment = Alignment.CenterVertically) {
                TextField(
                    typed, { typed = it }, placeholder = { Text("Type, then Send (goes into the page)") }, singleLine = true,
                    modifier = Modifier.weight(1f).clip(RoundedCornerShape(14.dp)),
                    colors = TextFieldDefaults.colors(focusedContainerColor = ClaraColors.Raised, unfocusedContainerColor = ClaraColors.Raised,
                        focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent),
                )
                Spacer(Modifier.width(6.dp))
                OutlinedButton(onClick = { onType(typed); typed = "" }, shape = RoundedCornerShape(14.dp)) { Text("Send", color = ClaraColors.Text) }
            }
        }
        BoxWithConstraints(Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(0.dp))) {
            val boxW = constraints.maxWidth.toFloat()
            val boxH = constraints.maxHeight.toFloat()
            val fit = minOf(boxW / dw, boxH / dh)                 // page px -> screen px at zoom 1
            val left = (boxW - dw * fit) / 2f
            fun pageOf(p: Offset): Pair<Float, Float> {          // screen point -> page (CSS) point
                val c = (p - pan) / zoom
                return ((c.x - left) / fit) to (c.y / fit)
            }
            Image(
                frame, "Clara's browser", contentScale = ContentScale.FillBounds,
                modifier = Modifier
                    .graphicsLayer {
                        scaleX = zoom; scaleY = zoom; translationX = pan.x; translationY = pan.y
                        transformOrigin = androidx.compose.ui.graphics.TransformOrigin(0f, 0f)
                    }
                    .padding(start = with(androidx.compose.ui.platform.LocalDensity.current) { left.toDp() })
                    .size(with(androidx.compose.ui.platform.LocalDensity.current) { (dw * fit).toDp() },
                          with(androidx.compose.ui.platform.LocalDensity.current) { (dh * fit).toDp() }),
            )
            Box(Modifier.fillMaxSize().pointerInput(dw, dh, fit) {
                awaitEachGesture {
                    val down = awaitFirstDown()
                    var multi = false
                    var dragged = 0f
                    do {
                        val ev = awaitPointerEvent()
                        val pressed = ev.changes.count { it.pressed }
                        if (pressed >= 2) {                       // two fingers: zoom and move the view
                            multi = true
                            val z = ev.calculateZoom()
                            val c = ev.calculateCentroid()
                            val newZoom = (zoom * z).coerceIn(1f, 4f)
                            pan = (c - (c - pan) * (newZoom / zoom)) + ev.calculatePan()
                            zoom = newZoom
                            val maxX = 0f; val minX = boxW - boxW * zoom
                            val maxY = 0f; val minY = boxH - boxH * zoom
                            pan = Offset(pan.x.coerceIn(minX, maxX), pan.y.coerceIn(minY, maxY))
                            ev.changes.forEach { it.consume() }
                        } else if (!multi && pressed == 1) {      // one finger: scroll the page
                            val ch = ev.changes.first { it.pressed }
                            val d = ch.position - ch.previousPosition
                            dragged += kotlin.math.abs(d.x) + kotlin.math.abs(d.y)
                            if (dragged > viewConfiguration.touchSlop && (d.y != 0f || d.x != 0f)) {
                                val (x, y) = pageOf(ch.position)
                                onMouse("mouseWheel", x, y, ""","deltaX":${-d.x / (fit * zoom)},"deltaY":${-d.y / (fit * zoom)}""")
                                ch.consume()
                            }
                        }
                    } while (ev.changes.any { it.pressed })
                    if (!multi && dragged <= viewConfiguration.touchSlop) {   // a tap: click there
                        val (x, y) = pageOf(down.position)
                        onMouse("mouseMoved", x, y, ""); onMouse("mousePressed", x, y, ""); onMouse("mouseReleased", x, y, "")
                    }
                }
            })
        }
    }
}
