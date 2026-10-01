package info.thewiderlens.clara.voice

import org.junit.Assert.assertEquals
import org.junit.Test

class SentenceSplitterTest {
    /** Feeds a reply the way it streams in (a few characters at a time) and returns everything that would be spoken. */
    private fun stream(reply: String, step: Int = 7): List<String> {
        val s = SentenceSplitter()
        val out = mutableListOf<String>()
        var i = step
        while (i < reply.length) { out += s.feed(reply.substring(0, i), final = false); i += step }
        out += s.feed(reply, final = true)
        return out
    }

    @Test fun speaksEverythingExactlyOnce() {
        val reply = "Try a lemon garlic pan roast. Brown the thighs first, then simmer them in broth! Want the full recipe in the chat?"
        val spoken = stream(reply)
        assertEquals(reply.replace(Regex("\\s+"), " "), spoken.joinToString(" "))
    }

    @Test fun shortSentencesAreKeptTogether() {
        val spoken = stream("Sure! Done. I set it for six o'clock tonight, and I'll ping you then.")
        assertEquals(listOf("Sure! Done. I set it for six o'clock tonight, and I'll ping you then."), spoken)
    }

    @Test fun firstSentenceIsReadyBeforeTheReplyEnds() {
        val s = SentenceSplitter()
        val early = s.feed("That's a great question about bonsai care. Water it when the top", final = false)
        assertEquals(listOf("That's a great question about bonsai care."), early)
        assertEquals(listOf("Water it when the top inch of soil is dry."), s.feed("That's a great question about bonsai care. Water it when the top inch of soil is dry.", final = true))
    }

    @Test fun emptyAndEmojiOnlyAreSkipped() {
        assertEquals(emptyList<String>(), stream("🌱"))
        assertEquals(emptyList<String>(), stream(""))
    }
}
