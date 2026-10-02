package info.thewiderlens.clara.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** One reconnecting socket per viewer, released with its Compose lifecycle. */
class BrowserConnection(
    private val api: BridgeApi,
    private val scope: CoroutineScope,
    private val listener: WebSocketListener,
    private val onSocket: (WebSocket?) -> Unit = {},
) {
    private var socket: WebSocket? = null
    private var retry: Job? = null
    private var closed = false
    private var delayMs = 500L

    init { connect() }

    private fun connect() {
        if (closed) return
        socket = api.http.newWebSocket(
            Request.Builder().url(api.baseUrl.replaceFirst("http", "ws") + "/v1/screen/stream").build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    scope.launch { if (!closed && socket === webSocket) {
                        delayMs = 500L; onSocket(webSocket); listener.onOpen(webSocket, response)
                    } }
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    scope.launch { if (!closed && socket === webSocket) listener.onMessage(webSocket, text) }
                }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, reason)
                }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    disconnected(webSocket, null, null)
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    disconnected(webSocket, t, response)
                }
            },
        )
    }

    private fun disconnected(webSocket: WebSocket, error: Throwable?, response: Response?) {
        scope.launch {
            if (closed || socket !== webSocket) return@launch
            socket = null; onSocket(null)
            listener.onFailure(webSocket, error ?: java.io.IOException("Browser connection closed"), response)
            retry?.cancel()
            retry = scope.launch {
                delay(delayMs)
                delayMs = (delayMs * 2).coerceAtMost(10_000L)
                connect()
            }
        }
    }

    fun close() {
        closed = true; retry?.cancel(); socket?.cancel(); socket = null; onSocket(null)
    }
}
