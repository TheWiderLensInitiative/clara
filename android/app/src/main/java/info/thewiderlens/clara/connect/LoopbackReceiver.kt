package info.thewiderlens.clara.connect

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.net.URLDecoder

/**
 * Catches the OAuth redirect on http://127.0.0.1:<port>/cb (the loopback method Google recommends for installed apps).
 * The browser on this phone lands here after sign-in; we read the one-time code, show a "you can go back" page
 * that jumps back into Clara, and hand the code to the Bridge. Nothing leaves the phone except to the Bridge.
 */
class LoopbackReceiver(port: Int = 53682) {
    // a fixed port, because Spotify, Dropbox and Microsoft only accept the exact redirect the user registered
    private val server = ServerSocket().apply {
        reuseAddress = true
        bind(java.net.InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 1)
        soTimeout = 1000
    }
    val redirectUri = "http://127.0.0.1:${server.localPort}/cb"

    data class Result(val code: String?, val state: String?, val error: String?)

    @Volatile private var accepted: java.net.Socket? = null

    suspend fun await(expectedState: String?): Result = kotlinx.coroutines.suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { close() }
        val worker = Thread {
            try {
                require(!expectedState.isNullOrBlank()) { "Sign-in did not include a state token" }
                val deadline = System.currentTimeMillis() + 10 * 60 * 1000
                while (continuation.isActive && System.currentTimeMillis() < deadline) {
                    val socket = try { server.accept() } catch (_: SocketTimeoutException) { continue }
                    accepted = socket
                    socket.use { client ->
                        client.soTimeout = 5000
                        val line = try {
                            val input = client.getInputStream()
                            val bytes = java.io.ByteArrayOutputStream()
                            while (bytes.size() < 8192) {
                                val c = input.read()
                                if (c < 0 || c == 10) break
                                bytes.write(c)
                            }
                            bytes.toString("UTF-8").trimEnd('\r')
                        } catch (_: SocketTimeoutException) { return@use }
                        val path = line.split(" ").getOrNull(1) ?: ""
                        val query = path.substringAfter('?', "").split('&').filter { '=' in it }.associate {
                            URLDecoder.decode(it.substringBefore('='), "UTF-8") to URLDecoder.decode(it.substringAfter('='), "UTF-8")
                        }
                        val valid = path.substringBefore('?') == "/cb" && query["state"] == expectedState &&
                            (query["code"] != null || query["error"] != null)
                        val body = if (valid) "Sign-in received. Return to Clara to finish connecting." else "Unrecognized callback. Continue sign-in in your browser."
                        val data = body.toByteArray()
                        client.getOutputStream().write(("HTTP/1.1 ${if (valid) "200 OK" else "400 Bad Request"}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: ${data.size}\r\nConnection: close\r\n\r\n").toByteArray() + data)
                        if (valid && continuation.isActive) continuation.resumeWith(kotlin.Result.success(Result(query["code"], query["state"], query["error"])))
                    }
                    accepted = null
                    if (!continuation.isActive) break
                }
                if (continuation.isActive) continuation.resumeWith(kotlin.Result.success(Result(null, null, "timed out")))
            } catch (error: Exception) {
                if (continuation.isActive) continuation.resumeWith(kotlin.Result.failure(error))
            } finally { close() }
        }
        worker.isDaemon = true
        worker.name = "clara-oauth-callback"
        worker.start()
    }

    fun close() { runCatching { accepted?.close() }; runCatching { server.close() } }
}
