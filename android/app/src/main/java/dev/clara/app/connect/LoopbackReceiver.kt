package dev.clara.app.connect

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
        soTimeout = 10 * 60 * 1000
    }
    val redirectUri = "http://127.0.0.1:${server.localPort}/cb"

    data class Result(val code: String?, val state: String?, val error: String?)

    suspend fun await(): Result = withContext(Dispatchers.IO) {
        while (true) {
            val sock = try { server.accept() } catch (e: SocketTimeoutException) { return@withContext Result(null, null, "timed out") }
            sock.use { s ->
                val line = s.getInputStream().bufferedReader().readLine() ?: ""
                val path = line.split(" ").getOrNull(1) ?: ""
                if (!path.startsWith("/cb")) {   // e.g. the browser asking for /favicon.ico
                    s.getOutputStream().write("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
                    return@use
                }
                val q = path.substringAfter('?', "").split('&').filter { '=' in it }
                    .associate { URLDecoder.decode(it.substringBefore('='), "UTF-8") to URLDecoder.decode(it.substringAfter('='), "UTF-8") }
                val ok = q["code"] != null && q["error"] == null
                val html = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
                    <style>body{background:#000;color:#fff;font-family:sans-serif;text-align:center;padding:60px 24px}
                    a{display:inline-block;margin-top:24px;padding:14px 28px;border-radius:24px;background:linear-gradient(90deg,#0A58E0,#5B3CF5,#D53CD1);color:#fff;text-decoration:none}</style>
                    </head><body><h2>${if (ok) "Connected ✓" else "Sign-in didn't finish"}</h2>
                    <p>${if (ok) "You can go back to Clara." else "Go back to Clara and try again."}</p>
                    <a href="clara://connected">Back to Clara</a>
                    <script>setTimeout(function(){location.href='clara://connected'},600)</script></body></html>"""
                val body = html.toByteArray()
                s.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n").toByteArray() + body)
                s.getOutputStream().flush()
                return@withContext Result(q["code"], q["state"], q["error"])
            }
        }
        @Suppress("UNREACHABLE_CODE") Result(null, null, "closed")
    }

    fun close() = runCatching { server.close() }
}
