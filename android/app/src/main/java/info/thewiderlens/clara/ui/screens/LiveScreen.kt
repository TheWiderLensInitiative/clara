package info.thewiderlens.clara.ui.screens

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
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
fun LiveScreenPage(state: UiState, api: BridgeApi?, onBack: () -> Unit) {
    var frame by remember { mutableStateOf<ImageBitmap?>(null) }
    var device by remember { mutableStateOf(1280f to 720f) }
    var online by remember { mutableStateOf(false) }
    var takeover by remember { mutableStateOf(false) }
    var url by remember { mutableStateOf("") }
    var socket by remember { mutableStateOf<WebSocket?>(null) }
    var typed by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    DisposableEffect(api) {
        val ws = api?.let { a ->
            a.http.newWebSocket(
                Request.Builder().url(a.baseUrl.replaceFirst("http", "ws") + "/v1/screen/stream").build(),
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        val m = runCatching { JSONObject(text) }.getOrNull() ?: return
                        when (m.optString("type")) {
                            "frame" -> scope.launch {
                                val seq = m.optLong("seq")
                                val md = m.optJSONObject("metadata")
                                val bmp = withContext(Dispatchers.Default) {
                                    val bytes = Base64.decode(m.optString("data"), Base64.DEFAULT)
                                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
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
                            "online" -> { online = true; takeover = m.optBoolean("takeover") }
                            "offline" -> { online = false; frame = null }
                            "takeover" -> takeover = m.optBoolean("on")
                            "url" -> url = m.optString("url")
                        }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { online = false }
                },
            )
        }
        socket = ws
        onDispose { ws?.close(1000, "closed"); socket = null }
    }

    fun send(json: String) { socket?.send(json) }
    fun mouse(type: String, x: Float, y: Float, extra: String = "") =
        send("""{"type":"input_mouse","eventType":"$type","x":$x,"y":$y,"button":"left","clickCount":1$extra}""")
    fun key(key: String, code: String, vk: Int, text: String? = null) {
        val t = text?.let { ""","text":${JSONObject.quote(it)}""" } ?: ""
        send("""{"type":"input_keyboard","eventType":"keyDown","key":${JSONObject.quote(key)},"code":"$code","windowsVirtualKeyCode":$vk$t}""")
        send("""{"type":"input_keyboard","eventType":"keyUp","key":${JSONObject.quote(key)},"code":"$code","windowsVirtualKeyCode":$vk}""")
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
