package info.thewiderlens.clara.voice

import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume

enum class VoicePhase { Idle, Listening, Thinking, Speaking }

/**
 * One voice conversation: the phone's speech recognizer listens, Clara's replies are spoken sentence by sentence
 * with her Kokoro voice from the PC (the next sentence is fetched while the current one plays). If the PC voice
 * can't be reached, Android's own text-to-speech fills in.
 */
class VoiceSession(
    private val context: Context,
    private val scope: CoroutineScope,
    private val fetchSpeech: suspend (String) -> ByteArray?,
) {
    private val _phase = MutableStateFlow(VoicePhase.Idle)
    val phase: StateFlow<VoicePhase> = _phase
    val heardSoFar = MutableStateFlow("")     // live transcript while listening
    val caption = MutableStateFlow("")        // the sentence Clara is saying
    val level = MutableStateFlow(0f)          // mic loudness 0..1 for the listening animation
    val problem = MutableStateFlow<String?>(null)

    /** Called with what the user said. */
    var onHeard: (String) -> Unit = {}
    /** Called when Clara finished speaking a whole reply. */
    var onSpokenAll: () -> Unit = {}

    private var recognizer: SpeechRecognizer? = null
    private var player: MediaPlayer? = null
    private var fallback: TextToSpeech? = null
    private var fallbackReady = false

    private val ready = HashMap<String, ByteArray>()   // phrases made ahead of time, so they play instantly

    /** Make short phrases (like "On it, one sec.") ahead of time. */
    fun prepare(phrases: List<String>) {
        scope.launch { for (p in phrases) if (p !in ready) runCatching { fetchSpeech(p) }.getOrNull()?.let { ready[p] = it } }
    }

    private var sentences = Channel<String>(Channel.UNLIMITED)
    private var speaker: Job? = null
    private var queued = 0
    private var replyFinished = false

    // --- listening ---------------------------------------------------------------------------
    fun listen() {
        stopSpeaking()
        problem.value = null
        heardSoFar.value = ""
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            problem.value = "Speech recognition isn't available on this phone."
            _phase.value = VoicePhase.Idle
            return
        }
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) { _phase.value = VoicePhase.Listening }
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) { level.value = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f) }
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() { level.value = 0f }
                override fun onError(error: Int) {
                    level.value = 0f
                    _phase.value = VoicePhase.Idle
                    problem.value = when (error) {
                        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> null  // just silence
                        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Clara needs microphone permission."
                        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Speech recognition needs a connection."
                        else -> "Didn't catch that."
                    }
                }
                override fun onResults(results: Bundle?) {
                    level.value = 0f
                    val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim().orEmpty()
                    if (text.isBlank()) { _phase.value = VoicePhase.Idle; return }
                    heardSoFar.value = text
                    _phase.value = VoicePhase.Thinking
                    beginReply()
                    onHeard(text)
                }
                override fun onPartialResults(partial: Bundle?) {
                    partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.let { heardSoFar.value = it }
                }
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
            startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                // end the turn sooner after the user stops talking (honored by Google's recognizer; others ignore it)
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 700L)
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 500L)
                .putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName))
        }
        _phase.value = VoicePhase.Listening
    }

    fun stopListening() {
        recognizer?.cancel()
        level.value = 0f
        if (_phase.value == VoicePhase.Listening) _phase.value = VoicePhase.Idle
    }

    // --- speaking ----------------------------------------------------------------------------
    /** Start a fresh reply: nothing queued yet, reply not finished. */
    fun beginReply() {
        stopSpeaking()
        replyFinished = false
        queued = 0
        sentences = Channel(Channel.UNLIMITED)
        val input = sentences
        val audio = Channel<Pair<String, Deferred<ByteArray?>>>(capacity = 2)  // fetch ahead while speaking
        speaker = scope.launch {
            launch { for (s in input) audio.send(s to async { ready[s] ?: runCatching { fetchSpeech(s) }.getOrNull() }) ; audio.close() }
            for ((text, wav) in audio) {
                _phase.value = VoicePhase.Speaking
                caption.value = text
                val bytes = wav.await()
                if (bytes != null) playWav(bytes) else speakFallback(text)
                queued--
                if (queued <= 0 && !replyFinished) { caption.value = ""; _phase.value = VoicePhase.Thinking }  // said "one sec", still working
                checkDone()
            }
        }
    }

    /** Queue one sentence of Clara's reply. */
    fun say(sentence: String) {
        if (sentence.isBlank()) return
        queued++
        sentences.trySend(sentence)
    }

    /** No more sentences are coming for this reply. */
    fun finishReply() {
        replyFinished = true
        sentences.close()
        checkDone()
    }

    private fun checkDone() {
        if (replyFinished && queued <= 0) {
            caption.value = ""
            _phase.value = VoicePhase.Idle
            onSpokenAll()
        }
    }

    fun stopSpeaking() {
        speaker?.cancel()
        speaker = null
        sentences.close()
        player?.runCatching { stop(); release() }
        player = null
        fallback?.stop()
        caption.value = ""
        if (_phase.value == VoicePhase.Speaking) _phase.value = VoicePhase.Idle
    }

    private suspend fun playWav(bytes: ByteArray) {
        val f = File(context.cacheDir, "clara-voice-${System.nanoTime()}.wav").apply { writeBytes(bytes) }
        try {
            suspendCancellableCoroutine { cont ->
                val mp = MediaPlayer()
                player = mp
                runCatching {
                    mp.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    mp.setDataSource(f.absolutePath)
                    mp.setOnCompletionListener { if (cont.isActive) cont.resume(Unit) }
                    mp.setOnErrorListener { _, _, _ -> if (cont.isActive) cont.resume(Unit); true }
                    mp.prepare()
                    mp.start()
                }.onFailure { if (cont.isActive) cont.resume(Unit) }
                cont.invokeOnCancellation { runCatching { mp.stop() } }
            }
        } finally {
            player?.runCatching { release() }
            player = null
            f.delete()
        }
    }

    private suspend fun speakFallback(text: String) {
        val tts = fallback ?: suspendCancellableCoroutine { cont ->
            var engine: TextToSpeech? = null
            engine = TextToSpeech(context) { status ->
                fallbackReady = status == TextToSpeech.SUCCESS
                if (cont.isActive) cont.resume(engine!!)
            }
        }.also { fallback = it }
        if (!fallbackReady) return
        suspendCancellableCoroutine { cont ->
            val id = "u${System.nanoTime()}"
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {}
                override fun onDone(utteranceId: String?) { if (utteranceId == id && cont.isActive) cont.resume(Unit) }
                @Deprecated("Deprecated in Java") override fun onError(utteranceId: String?) { if (cont.isActive) cont.resume(Unit) }
            })
            tts.speak(text.replace(Regex("[*_`#]"), ""), TextToSpeech.QUEUE_FLUSH, null, id)
            cont.invokeOnCancellation { tts.stop() }
        }
    }

    fun release() {
        stopSpeaking()
        recognizer?.destroy()
        recognizer = null
        fallback?.shutdown()
        fallback = null
    }
}

/** Splits a reply into speakable sentences as it streams in. */
class SentenceSplitter {
    private var spoken = 0
    private val said = StringBuilder()   // everything spoken for this reply, normalized, so the final text isn't read twice
    private val boundary = Regex("""(?<=[.!?…])["')\]]*\s+|\n{2,}""")
    private val clause = Regex("""(?<=[,;:—–])\s+""")

    /** New complete sentences in [text] (the reply so far); keeps short fragments together so speech flows. */
    fun feed(text: String, final: Boolean): List<String> {
        if (spoken > text.length) spoken = 0
        val rest = text.substring(spoken)
        val out = mutableListOf<String>()
        var consumed = 0
        var chunk = StringBuilder()
        for (m in boundary.findAll(rest)) {
            chunk.append(rest, consumed, m.range.last + 1)
            consumed = m.range.last + 1
            if (chunk.trim().length >= 25) { out += chunk.toString().trim(); chunk = StringBuilder() }
        }
        if (!final && out.isEmpty() && said.isEmpty()) {
            // Start talking sooner: the first piece of a reply may end at a comma or dash, so it is quick to voice.
            clause.findAll(rest).firstOrNull { it.range.first >= 20 }?.let { m ->
                out += rest.substring(0, m.range.last + 1).trim()
                consumed = m.range.last + 1
                chunk = StringBuilder()
            }
        }
        if (final) {
            chunk.append(rest.substring(consumed))
            consumed = rest.length
        } else if (chunk.isNotEmpty()) {
            consumed -= chunk.length  // not long enough yet: wait for more text
            chunk = StringBuilder()
        }
        if (chunk.isNotBlank()) out += chunk.toString().trim()
        spoken += consumed
        return emit(out)
    }

    /**
     * The finished reply. While a task runs, its text streams in pieces and is spoken as it goes; the final message can
     * differ slightly (e.g. "Got it. Here's…" instead of "Here's…"), so only sentences not already said are spoken.
     */
    fun finish(text: String): List<String> {
        if (said.isEmpty()) return feed(text, final = true)
        spoken = 0
        val fresh = text.split(boundary).map { it.trim() }.filter { s -> norm(s).let { it.isNotEmpty() && !said.contains(it) } }
        if (fresh.sumOf { it.length } < 40) return emptyList()   // only filler like "Got it." is new: the reply was already said
        val out = mutableListOf<String>()
        var chunk = ""
        for (s in fresh) {
            chunk = (chunk + " " + s).trim()
            if (chunk.length >= 25) { out += chunk; chunk = "" }
        }
        if (chunk.isNotBlank()) out += chunk
        return emit(out)
    }

    fun reset() { spoken = 0; said.setLength(0) }

    private fun emit(parts: List<String>): List<String> =
        parts.map(::speakable).filter { it.any(Char::isLetterOrDigit) }.onEach { said.append(norm(it)) }

    private fun norm(s: String) = speakable(s).lowercase().filter(Char::isLetterOrDigit)
}

/** What to say and show for a piece of reply text: no Markdown symbols, list dashes or line breaks. */
fun speakable(text: String): String =
    text.replace(Regex("""\*\*|__|`|(?m)^#+\s*"""), "")
        .replace(Regex("""(?m)^\s*(?:[-•*]|\d+[.)])\s+"""), "")
        .replace(Regex("""\s*\n\s*"""), " ")
        .trim()
