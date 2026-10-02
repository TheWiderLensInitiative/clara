package info.thewiderlens.clara.data

import java.io.InputStream
import java.io.ByteArrayOutputStream

fun InputStream.readBounded(maxBytes: Int = 25 * 1024 * 1024): ByteArray {
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(8192)
    var total = 0
    while (true) {
        val count = read(buffer)
        if (count < 0) break
        total += count
        require(total <= maxBytes) { "That file is over 25 MB" }
        output.write(buffer, 0, count)
    }
    return output.toByteArray()
}
