package info.thewiderlens.clara.data

import java.io.ByteArrayInputStream
import java.io.InputStream
import org.junit.Assert.*
import org.junit.Test

class BoundedInputTest {
    @Test fun preservesFileAtLimit() {
        val bytes = ByteArray(8193) { (it % 127).toByte() }
        assertArrayEquals(bytes, ByteArrayInputStream(bytes).readBounded(bytes.size))
    }

    @Test fun rejectsOversizeWithoutReadingWholeFile() {
        var consumed = 0
        val source = object : InputStream() {
            override fun read(): Int { consumed++; return 1 }
        }
        try {
            source.readBounded(8192)
            fail("oversize input accepted")
        } catch (_: IllegalArgumentException) {
            assertTrue("unbounded source was drained", consumed <= 16384)
        }
    }

    @Test fun acceptsEmptyFile() {
        assertArrayEquals(byteArrayOf(), ByteArrayInputStream(byteArrayOf()).readBounded(0))
    }

    @Test fun preservesShortReads() {
        val source = object : ByteArrayInputStream("small chunks".toByteArray()) {
            override fun read(b: ByteArray, off: Int, len: Int) = super.read(b, off, minOf(len, 2))
        }
        assertEquals("small chunks", String(source.readBounded(20)))
    }
}
