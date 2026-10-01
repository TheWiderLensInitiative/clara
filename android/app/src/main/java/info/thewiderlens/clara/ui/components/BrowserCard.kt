package info.thewiderlens.clara.ui.components

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import info.thewiderlens.clara.data.BridgeApi
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
 * Clara's browser, right in the chat while she uses it (like Muse): a live, watch-only preview of her screen with an
 * "Open browser" button for the full Screen page, where you can also take over. Taps on the preview never reach the page.
 */
@Composable
fun LiveBrowserCard(api: BridgeApi?, onOpen: () -> Unit) {
    var frame by remember { mutableStateOf<ImageBitmap?>(null) }
    var url by remember { mutableStateOf("") }
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
                                val bmp = withContext(Dispatchers.Default) {
                                    val bytes = Base64.decode(m.optString("data"), Base64.DEFAULT)
                                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
                                }
                                if (bmp != null) frame = bmp
                                webSocket.send("""{"type":"ack","seq":$seq}""")
                            }
                            "url" -> url = m.optString("url")
                        }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {}
                },
            )
        }
        onDispose { ws?.close(1000, "closed") }
    }
    BrowserFrame(frame, url, live = true, onOpen = onOpen)
}

/** The page Clara ended on, kept under her reply. */
@Composable
fun BrowserSnapshotCard(path: String, url: String, load: suspend (String) -> ByteArray?, onOpen: () -> Unit) {
    var bmp by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        val bytes = runCatching { load(path) }.getOrNull()
        bmp = bytes?.let { withContext(Dispatchers.Default) { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() } }
    }
    // Her browser has usually closed by now, so the button opens that page in the phone's own browser instead.
    val context = androidx.compose.ui.platform.LocalContext.current
    val openPage: () -> Unit = if (url.startsWith("http")) {
        { runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) } }
    } else onOpen
    BrowserFrame(bmp, url, live = false, onOpen = openPage, label = if (url.startsWith("http")) "Open page" else "Open browser")
}

@Composable
private fun BrowserFrame(frame: ImageBitmap?, url: String, live: Boolean, onOpen: () -> Unit, label: String = "Open browser") {
    val shape = RoundedCornerShape(20.dp)
    Column(
        Modifier.padding(vertical = 6.dp).widthIn(max = 340.dp).fillMaxWidth().clip(shape)
            .background(ClaraColors.Panel).border(1.dp, ClaraColors.Line, shape).padding(10.dp),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 10f).clip(RoundedCornerShape(14.dp)).background(ClaraColors.Raised).clickable(onClick = onOpen)) {
            if (frame != null) {
                Image(frame, "Clara's browser", Modifier.fillMaxSize(), contentScale = ContentScale.Crop, alignment = Alignment.TopCenter)
            } else {
                Text(
                    if (live) "Opening Clara's browser…" else "Clara's browser",
                    style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted, modifier = Modifier.align(Alignment.Center),
                )
            }
            if (live) {
                Row(
                    Modifier.padding(8.dp).clip(RoundedCornerShape(10.dp)).background(ClaraColors.Black.copy(alpha = 0.6f))
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.size(7.dp).clip(CircleShape).background(ClaraColors.Danger))
                    Spacer(Modifier.width(5.dp))
                    Text("Live", style = MaterialTheme.typography.labelSmall, color = ClaraColors.Text)
                }
            }
        }
        val host = runCatching { java.net.URI(url).host?.removePrefix("www.") }.getOrNull()
        if (!host.isNullOrBlank()) {
            Text(host, style = MaterialTheme.typography.labelMedium, color = ClaraColors.Muted, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 4.dp, top = 8.dp))
        }
        Box(
            Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(ClaraColors.Raised)
                .clickable(onClick = onOpen).padding(vertical = 11.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, style = MaterialTheme.typography.titleSmall, color = ClaraColors.Text)
        }
    }
}
