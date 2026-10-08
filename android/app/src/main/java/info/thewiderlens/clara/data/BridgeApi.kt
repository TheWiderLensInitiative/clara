package info.thewiderlens.clara.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.io.IOException
import java.util.concurrent.TimeUnit

class BridgeException(val code: Int, message: String) : IOException(message)

/** Thin client for the Clara Bridge HTTP API. */
class BridgeApi(val baseUrl: String, private val token: String?) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val jsonType = "application/json".toMediaType()

    val http: OkHttpClient = shared.newBuilder()
        .addInterceptor { chain ->
            val req = chain.request().newBuilder()
            if (token != null) req.header("Authorization", "Bearer $token")
            chain.proceed(req.build())
        }
        .build()

    private val streamClient = http.newBuilder().readTimeout(0, TimeUnit.SECONDS).build()

    private fun url(path: String) = baseUrl.trimEnd('/') + path

    private suspend fun call(method: String, path: String, body: String? = null): String = withContext(Dispatchers.IO) {
        val rb = body?.toRequestBody(jsonType) ?: if (method == "POST") "{}".toRequestBody(jsonType) else null
        val req = Request.Builder().url(url(path)).method(method, rb).build()
        http.newCall(req).execute().use { resp -> read(resp) }
    }

    private fun read(resp: Response): String {
        val text = resp.body.string()
        if (!resp.isSuccessful) {
            val detail = runCatching { json.parseToJsonElement(text).jsonObject["detail"]?.jsonPrimitive?.contentOrNull }.getOrNull()
            throw BridgeException(resp.code, detail ?: "HTTP ${resp.code}")
        }
        return text
    }

    private fun obj(vararg pairs: Pair<String, String>) =
        json.encodeToString(JsonObject.serializer(), JsonObject(pairs.associate { (k, v) -> k to kotlinx.serialization.json.JsonPrimitive(v) }))

    suspend fun health(): Health = json.decodeFromString(call("GET", "/v1/health"))
    suspend fun addresses(): Addresses = json.decodeFromString(call("GET", "/v1/addresses"))

    /** Quick reachability check (short timeouts) used to pick between home Wi-Fi and Tailscale. */
    suspend fun reachable(timeoutMs: Long = 2500): Boolean = kotlinx.coroutines.suspendCancellableCoroutine { continuation ->
        val quick = http.newBuilder().connectTimeout(timeoutMs, TimeUnit.MILLISECONDS).readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
            .callTimeout(timeoutMs + 500, TimeUnit.MILLISECONDS).build()
        val call = quick.newCall(Request.Builder().url(url("/v1/addresses")).build())
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWith(Result.success(false))
            }
            override fun onResponse(call: okhttp3.Call, response: Response) {
                val success = response.use { it.isSuccessful }
                if (continuation.isActive) continuation.resumeWith(Result.success(success))
            }
        })
    }
    suspend fun pair(code: String, deviceName: String): PairResponse =
        json.decodeFromString(call("POST", "/v1/pair", obj("code" to code, "device_name" to deviceName)))

    suspend fun conversations(): List<Conversation> = json.decodeFromString<ConversationList>(call("GET", "/v1/conversations")).conversations
    suspend fun deleteConversation(cid: String) { call("DELETE", "/v1/conversations/$cid") }
    suspend fun newConversation(): Conversation = json.decodeFromString(call("POST", "/v1/conversations"))
    suspend fun messages(cid: String): List<Message> = json.decodeFromString<MessageList>(call("GET", "/v1/conversations/$cid/messages")).messages
    suspend fun send(cid: String, text: String, attachments: List<String> = emptyList(), voice: Boolean = false): SendResponse {
        val body = JsonObject(mapOf(
            "text" to kotlinx.serialization.json.JsonPrimitive(text),
            "voice" to kotlinx.serialization.json.JsonPrimitive(voice),
            "attachments" to kotlinx.serialization.json.JsonArray(attachments.map { kotlinx.serialization.json.JsonPrimitive(it) }),
        ))
        return json.decodeFromString(call("POST", "/v1/conversations/$cid/messages", json.encodeToString(JsonObject.serializer(), body)))
    }

    /** Clara's voice for one sentence (WAV), spoken by Kokoro on the PC. */
    suspend fun tts(text: String): ByteArray = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/v1/tts")).post(obj("text" to text).toRequestBody(jsonType)).build()
        http.newCall(req).execute().use { r -> if (r.isSuccessful) r.body.bytes() else throw BridgeException(r.code, "voice unavailable") }
    }
    suspend fun voiceSettings(): VoiceSettings = json.decodeFromString(call("GET", "/v1/voice"))
    suspend fun setVoice(voice: String): VoiceSettings = json.decodeFromString(call("PUT", "/v1/voice", obj("voice" to voice)))

    /** Photos and files go to Clara's workspace (uploads/); the returned path is attached to the next message. */
    suspend fun upload(name: String, bytes: ByteArray, mime: String): Upload = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/v1/uploads?name=" + java.net.URLEncoder.encode(name, "UTF-8")))
            .post(bytes.toRequestBody(mime.toMediaType())).build()
        json.decodeFromString(http.newCall(req).execute().use { read(it) })
    }
    suspend fun stop(cid: String) { call("POST", "/v1/conversations/$cid/stop") }

    suspend fun approvals(status: String? = "pending"): List<Approval> =
        json.decodeFromString<ApprovalList>(call("GET", "/v1/approvals" + (status?.let { "?status=$it" } ?: ""))).approvals
    suspend fun answer(approvalId: String, choice: String) { call("POST", "/v1/approvals/$approvalId", obj("choice" to choice)) }

    suspend fun activity(limit: Int = 200): List<ActivityItem> = json.decodeFromString<ActivityList>(call("GET", "/v1/activity?limit=$limit")).activity
    suspend fun upcoming(): List<Job> = json.decodeFromString<JobList>(call("GET", "/v1/upcoming")).jobs
    /** An open "Clara needs your help in her browser" request, if any (survives the app being closed). */
    suspend fun openHelp(): HelpRequest? =
        json.parseToJsonElement(call("GET", "/v1/screen/status")).jsonObject["help"]
            ?.takeIf { it !is kotlinx.serialization.json.JsonNull }?.let { json.decodeFromJsonElement<HelpRequest>(it) }
    suspend fun jobAction(id: String, action: String) { call("POST", "/v1/upcoming/$id/$action") }
    suspend fun deleteJob(id: String) { call("DELETE", "/v1/upcoming/$id") }
    suspend fun memory(): Memory = json.decodeFromString(call("GET", "/v1/memory"))

    fun screenshotUrl() = url("/v1/screenshots/latest")

    suspend fun goals(): List<Goal> = json.decodeFromString<GoalList>(call("GET", "/v1/goals")).goals
    suspend fun addGoal(title: String, area: String): Goal = json.decodeFromString(call("POST", "/v1/goals", obj("title" to title, "area" to area)))
    suspend fun setGoalDone(id: String, done: Boolean) { call("PATCH", "/v1/goals/$id", """{"done": $done}""") }
    suspend fun deleteGoal(id: String) { call("DELETE", "/v1/goals/$id") }
    suspend fun setCheckin(id: String, checkin: String, time: String, day: Int): Goal =
        json.decodeFromString(call("PATCH", "/v1/goals/$id", """{"checkin": "$checkin", "checkin_time": "$time", "checkin_day": $day}"""))
    suspend fun goalLog(id: String): List<GoalLogEntry> = json.decodeFromString<GoalLog>(call("GET", "/v1/goals/$id/log")).log
    suspend fun proactive(): ProactiveSettings = json.decodeFromString(call("GET", "/v1/proactive"))
    suspend fun setProactive(p: ProactiveSettings): ProactiveSettings = json.decodeFromString(call("PUT", "/v1/proactive",
        """{"proactive_daily": ${p.daily}, "proactive_time": "${p.time}", "quiet_start": "${p.quietStart}", "quiet_end": "${p.quietEnd}"}"""))
    /** Clara reaches out right now: kind = suggestions | checkin. */
    suspend fun proactiveNow(kind: String, goalId: String? = null) {
        call("POST", "/v1/proactive/now", if (goalId != null) obj("kind" to kind, "goal_id" to goalId) else obj("kind" to kind))
    }

    suspend fun library(): List<LibraryFile> = json.decodeFromString<LibraryList>(call("GET", "/v1/library")).files
    suspend fun recipes(): List<RecipeView> = json.decodeFromString<RecipeList>(call("GET", "/v1/recipes")).recipes
    suspend fun deleteRecipe(name: String) { call("DELETE", "/v1/recipes/" + java.net.URLEncoder.encode(name, "UTF-8")) }
    fun libraryUrl(path: String) = url("/v1/library/file?path=" + java.net.URLEncoder.encode(path, "UTF-8"))
    suspend fun deleteLibraryFile(path: String) { call("DELETE", "/v1/library/file?path=" + java.net.URLEncoder.encode(path, "UTF-8")) }
    suspend fun saveLibraryFile(path: String, text: String) {
        call("PUT", "/v1/library/file?path=" + java.net.URLEncoder.encode(path, "UTF-8"), obj("text" to text))
    }
    suspend fun bytes(fullUrl: String): ByteArray? = withContext(Dispatchers.IO) {
        http.newCall(Request.Builder().url(fullUrl).build()).execute().use { r -> if (r.isSuccessful) r.body.bytes() else null }
    }

    /** Only the non-secret index goes to the PC: name, site, username. */
    suspend fun setVaultIndex(entries: List<SavedLogin>) {
        val body = kotlinx.serialization.json.buildJsonObject {
            put("logins", kotlinx.serialization.json.JsonArray(entries.map { e ->
                kotlinx.serialization.json.buildJsonObject {
                    put("name", kotlinx.serialization.json.JsonPrimitive(e.name))
                    put("site", kotlinx.serialization.json.JsonPrimitive(e.site ?: ""))
                    put("username", kotlinx.serialization.json.JsonPrimitive(e.username ?: ""))
                }
            }))
        }
        call("PUT", "/v1/vault/index", body.toString())
    }
    suspend fun vaultRequests(): List<VaultRequest> = json.decodeFromString<VaultRequestList>(call("GET", "/v1/vault/requests")).requests
    suspend fun answerVault(id: String, sealed: info.thewiderlens.clara.vault.Sealed?) {
        val body = if (sealed == null) """{"approve": false}""" else json.encodeToString(info.thewiderlens.clara.vault.Sealed.serializer(), sealed)
        call("POST", "/v1/vault/requests/$id", body)
    }

    suspend fun apis(): List<ApiService> = json.decodeFromString<ApiServiceList>(call("GET", "/v1/apis")).apis
    suspend fun saveApi(name: String, baseUrl: String, authType: String, authName: String, key: String, notes: String, writePolicy: String) {
        call("POST", "/v1/apis", obj("name" to name, "base_url" to baseUrl, "auth_type" to authType, "auth_name" to authName,
            "key" to key, "notes" to notes, "write_policy" to writePolicy))
    }
    suspend fun deleteApi(name: String) { call("DELETE", "/v1/apis/" + java.net.URLEncoder.encode(name, "UTF-8")) }
    suspend fun apiRequests(): List<ApiRequest> = json.decodeFromString<ApiRequestList>(call("GET", "/v1/apis/requests")).requests
    suspend fun answerApi(id: String, choice: String) { call("POST", "/v1/apis/requests/$id", obj("choice" to choice)) }

    suspend fun cloud(): CloudState = json.decodeFromString(call("GET", "/v1/cloud"))
    suspend fun character(): CharacterView = json.decodeFromString(call("GET", "/v1/character"))
    suspend fun setCharacterPreset(name: String): CharacterView = json.decodeFromString(call("PUT", "/v1/character", obj("preset" to name)))
    suspend fun setCharacterStyle(style: info.thewiderlens.clara.ui.components.CharacterStyle): CharacterView {
        val body = JsonObject(mapOf("style" to json.encodeToJsonElement(info.thewiderlens.clara.ui.components.CharacterStyle.serializer(), style)))
        return json.decodeFromString(call("PUT", "/v1/character", json.encodeToString(JsonObject.serializer(), body)))
    }
    suspend fun undoCharacter(): CharacterView = json.decodeFromString(call("POST", "/v1/character/undo"))
    suspend fun connectors(): List<Connector> = json.decodeFromString<ConnectorList>(call("GET", "/v1/connectors")).connectors
    suspend fun setConnectorClient(p: String, id: String, secret: String): Connector =
        json.decodeFromString(call("PUT", "/v1/connectors/$p/client", obj("client_id" to id, "client_secret" to secret)))
    suspend fun setConnectorToken(p: String, fields: Map<String, String>): Connector {
        val body = JsonObject(mapOf("fields" to JsonObject(fields.mapValues { kotlinx.serialization.json.JsonPrimitive(it.value) })))
        return json.decodeFromString(call("PUT", "/v1/connectors/$p/token", json.encodeToString(JsonObject.serializer(), body)))
    }
    suspend fun startConnect(p: String, redirect: String): String =
        json.decodeFromString<StartUrl>(call("POST", "/v1/connectors/$p/start", obj("redirect_uri" to redirect))).url
    suspend fun startDevice(p: String): DeviceCode =
        json.decodeFromString<DeviceStart>(call("POST", "/v1/connectors/$p/start", obj("redirect_uri" to "http://127.0.0.1:53682/cb"))).device
    suspend fun finishConnect(p: String, state: String, code: String): Connector =
        json.decodeFromString(call("POST", "/v1/connectors/$p/finish", obj("state" to state, "code" to code)))
    suspend fun disconnect(p: String, forgetClient: Boolean): Connector =
        json.decodeFromString(call("DELETE", "/v1/connectors/$p?forget_client=$forgetClient"))
    suspend fun setConnectorPolicy(p: String, key: String, value: String): Connector =
        json.decodeFromString(call("PUT", "/v1/connectors/$p/policy", obj(key to value)))
    suspend fun spend(days: Int = 30): SpendSummary = json.decodeFromString(call("GET", "/v1/spend?days=$days"))
    suspend fun brand(): BrandKit = json.decodeFromString(call("GET", "/v1/brand"))
    suspend fun setBrand(b: BrandKit): BrandKit = json.decodeFromString(call("PUT", "/v1/brand", obj(
        "name" to b.name, "tagline" to b.tagline, "cta" to b.cta, "website" to b.website, "primary" to b.primary,
        "accent" to b.accent, "text" to b.text, "font" to b.font, "music" to b.music)))
    suspend fun setBrandLogo(bytes: ByteArray): BrandKit = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url("/v1/brand/logo")).post(bytes.toRequestBody("image/*".toMediaType())).build()
        json.decodeFromString(http.newCall(req).execute().use { read(it) })
    }
    suspend fun removeBrandLogo(): BrandKit = json.decodeFromString(call("DELETE", "/v1/brand/logo"))
    suspend fun videoModels(): List<VideoModel> = json.decodeFromString<VideoModelList>(call("GET", "/v1/cloud/video-models")).models
    suspend fun updateCloud(body: String): CloudState = json.decodeFromString(call("PUT", "/v1/cloud", body))
    suspend fun answerCloud(id: String, choice: String) { call("POST", "/v1/cloud/requests/$id", obj("choice" to choice)) }
    suspend fun answerBudget(id: String, accept: Boolean) { call("POST", "/v1/cloud/budget/$id", """{"accept": $accept}""") }

    suspend fun identity(): Identity = json.decodeFromString(call("GET", "/v1/identity"))
    suspend fun setIdentity(name: String, text: String) { call("PUT", "/v1/identity/$name", obj("text" to text)) }

    /** The Bridge's live event stream as a Flow. Completes when the connection drops; callers reconnect. */
    fun events(): Flow<ClaraEvent> = callbackFlow {
        val listener = object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                trySend(ClaraEvent.Connected)
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                try {
                    parse(type, data)?.let { if (trySend(it).isFailure) { close(); eventSource.cancel() } }
                } catch (e: Exception) {
                    close(); eventSource.cancel()
                }
            }

            override fun onClosed(eventSource: EventSource) {
                trySend(ClaraEvent.Disconnected("closed")); close()
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                trySend(ClaraEvent.Disconnected(t?.message ?: "HTTP ${response?.code}")); close()
            }
        }
        val source = EventSources.createFactory(streamClient).newEventSource(Request.Builder().url(url("/v1/events")).build(), listener)
        awaitClose { source.cancel() }
    }

    private fun parse(type: String?, data: String): ClaraEvent? {
        val o = runCatching { json.parseToJsonElement(data).jsonObject }.getOrNull() ?: return null
        fun s(k: String) = o[k]?.jsonPrimitive?.contentOrNull ?: ""
        return when (type) {
            "resync" -> ClaraEvent.Resync
            "message.routed" -> ClaraEvent.Routed(s("conversation_id"), s("message_id"), s("route"), s("source"))
            "message.delta" -> ClaraEvent.Delta(s("conversation_id"), s("text"))
            "message.completed" -> ClaraEvent.Completed(json.decodeFromJsonElement(o["message"]!!))
            "notification" -> ClaraEvent.Notification(json.decodeFromJsonElement(o["message"]!!))
            "character.changed" -> ClaraEvent.CharacterChanged(json.decodeFromJsonElement(o["style"]!!))
            "run.started" -> ClaraEvent.RunStarted(s("conversation_id"), s("run_id"), s("route"))
            "run.stopping" -> ClaraEvent.RunStopping(s("conversation_id"))
            "activity" -> ClaraEvent.Activity(s("conversation_id"), s("kind"), o["tool"]?.jsonPrimitive?.contentOrNull, o["detail"]?.jsonPrimitive?.contentOrNull)
            "screenshot.available" -> ClaraEvent.ScreenshotAvailable(s("conversation_id"))
            "approval.requested" -> ClaraEvent.ApprovalRequested(json.decodeFromJsonElement(o["approval"]!!))
            "approval.resolved" -> ClaraEvent.ApprovalResolved(s("conversation_id"), o["choice"]?.jsonPrimitive?.contentOrNull)
            "vault.request" -> ClaraEvent.VaultRequest(json.decodeFromJsonElement(o["request"]!!))
            "vault.resolved" -> ClaraEvent.VaultResolved(s("id"))
            "api.request" -> ClaraEvent.ApiRequest(json.decodeFromJsonElement(o["request"]!!))
            "api.resolved" -> ClaraEvent.ApiResolved(s("id"))
            "cloud.request" -> ClaraEvent.CloudRequest(json.decodeFromJsonElement(o["request"]!!))
            "cloud.resolved" -> ClaraEvent.CloudResolved(s("id"))
            "cloud.budget" -> ClaraEvent.BudgetSuggestion(json.decodeFromJsonElement(o["suggestion"]!!))
            "cloud.budget.resolved" -> ClaraEvent.BudgetResolved(s("id"))
            "help.requested" -> ClaraEvent.HelpRequested(json.decodeFromJsonElement(o["help"]!!))
            "help.resolved" -> ClaraEvent.HelpResolved(s("id"))
            else -> null
        }
    }

    companion object {
        private val shared = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }
}
