package dev.clara.app.ui

import android.graphics.BitmapFactory
import android.os.Build
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dev.clara.app.ClaraHub
import dev.clara.app.Link
import dev.clara.app.data.ActivityItem
import dev.clara.app.data.Approval
import dev.clara.app.data.BridgeApi
import dev.clara.app.data.ClaraEvent
import dev.clara.app.data.Conversation
import dev.clara.app.data.Job
import dev.clara.app.data.Memory
import dev.clara.app.data.Message
import dev.clara.app.ui.components.Mood
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request

const val NOTIFICATIONS_CONVERSATION = "clara-notifications"

/** A photo or file picked in the composer; path is set once it has uploaded to Clara's workspace. */
data class Draft(val id: Long, val name: String, val isImage: Boolean, val preview: androidx.compose.ui.graphics.ImageBitmap?, val path: String? = null, val failed: Boolean = false)

data class UiState(
    val drafts: List<Draft> = emptyList(),
    val voice: dev.clara.app.data.VoiceSettings = dev.clara.app.data.VoiceSettings(),
    val proactive: dev.clara.app.data.ProactiveSettings = dev.clara.app.data.ProactiveSettings(),
    val videoModels: List<dev.clara.app.data.VideoModel> = emptyList(),
    val brand: dev.clara.app.data.BrandKit = dev.clara.app.data.BrandKit(),
    val spend: dev.clara.app.data.SpendSummary? = null,
    val connectors: List<dev.clara.app.data.Connector> = emptyList(),
    val character: dev.clara.app.data.CharacterView = dev.clara.app.data.CharacterView(),
    val connectLink: String? = null,       // sign-in link while waiting for the browser to come back
    val connectBusy: Boolean = false,
    val brandLogoVersion: Int = 0,   // bumps when the logo changes, so previews reload
    val paired: Boolean? = null,            // null = still loading settings
    val bridgeUrl: String = "",
    val link: Link = Link.Offline,
    val via: String? = null,              // "home" (Wi-Fi) or "remote" (Tailscale)
    val remoteUrl: String? = null,        // the PC's Tailscale address, once it has one
    val conversations: List<Conversation> = emptyList(),
    val conversationId: String? = null,
    val messages: List<Message> = emptyList(),
    val streaming: String = "",
    val working: Boolean = false,
    val status: String = "",                 // "Searching the web…"
    val pending: List<Approval> = emptyList(),
    val activity: List<ActivityItem> = emptyList(),
    val upcoming: List<Job> = emptyList(),
    val memory: Memory = Memory(),
    val screenshot: ImageBitmap? = null,
    val showLive: Boolean = false,
    val unreadNotifications: Int = 0,
    val error: String? = null,
    val busyPairing: Boolean = false,
    val doneAt: Long = 0L,
    val goals: List<dev.clara.app.data.Goal> = emptyList(),
    val library: List<dev.clara.app.data.LibraryFile> = emptyList(),
    val identity: dev.clara.app.data.Identity = dev.clara.app.data.Identity(),
    val screenAt: Long = 0L,
    val logins: List<dev.clara.app.data.SavedLogin> = emptyList(),
    val vaultRequests: List<dev.clara.app.data.VaultRequest> = emptyList(),
    val apis: List<dev.clara.app.data.ApiService> = emptyList(),
    val apiRequests: List<dev.clara.app.data.ApiRequest> = emptyList(),
    val cloud: dev.clara.app.data.CloudState = dev.clara.app.data.CloudState(),
    val cloudRequests: List<dev.clara.app.data.CloudRequest> = emptyList(),
    val budgetSuggestions: List<dev.clara.app.data.BudgetSuggestion> = emptyList(),
)

class ClaraViewModel : ViewModel() {
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui

    private var api: BridgeApi? = null

    init {
        viewModelScope.launch {
            ClaraHub.api.collect { a ->
                api = a
                _ui.update { it.copy(paired = a != null, bridgeUrl = a?.baseUrl ?: it.bridgeUrl) }
                if (a != null) { refreshAll(); refreshLogins(); refreshApis(); refreshCloud() }
            }
        }
        viewModelScope.launch { ClaraHub.link.collect { l -> _ui.update { it.copy(link = l) }; if (l == Link.Online) refreshAll() } }
        viewModelScope.launch { ClaraHub.via.collect { v -> _ui.update { it.copy(via = v) } } }
        viewModelScope.launch { ClaraHub.currentPairing.collect { p -> _ui.update { it.copy(remoteUrl = p?.remoteUrl) } } }
        viewModelScope.launch { ClaraHub.api.collect { a -> if (a != null) _ui.update { it.copy(bridgeUrl = a.baseUrl) } } }
        viewModelScope.launch { ClaraHub.events.collect(::onEvent) }
    }

    private fun launchSafe(block: suspend () -> Unit) = viewModelScope.launch {
        try { block() } catch (e: Exception) {
            // this phone was unpaired on the PC: go back to the pairing screen instead of failing every call
            if (e is dev.clara.app.data.BridgeException && e.code == 401) { confirmUnpaired(); return@launch }
            _ui.update { it.copy(error = e.message ?: e.toString()) }
        }
    }

    /** Only forget the pairing when the PC really says this phone was removed (checked twice, a moment apart). */
    private fun confirmUnpaired() = viewModelScope.launch {
        repeat(2) {
            kotlinx.coroutines.delay(1500)
            val stillBad = try { api?.conversations(); false } catch (e: dev.clara.app.data.BridgeException) { e.code == 401 } catch (_: Exception) { false }
            if (!stillBad) return@launch
        }
        unpair()
    }

    fun clearError() = _ui.update { it.copy(error = null) }

    // --- pairing ---------------------------------------------------------------
    fun pair(url: String, code: String) = viewModelScope.launch {
        _ui.update { it.copy(busyPairing = true, error = null) }
        try {
            ClaraHub.pair(url, code.trim(), "${Build.MANUFACTURER} ${Build.MODEL}".trim())
        } catch (e: Exception) {
            _ui.update { it.copy(error = "Couldn't pair: ${e.message}") }
        } finally {
            _ui.update { it.copy(busyPairing = false) }
        }
    }

    fun unpair() = viewModelScope.launch { ClaraHub.unpair(); _ui.value = UiState(paired = false) }

    // --- loading -------------------------------------------------------------------
    fun refreshAll() = launchSafe {
        val a = api ?: return@launchSafe
        val convs = a.conversations()
        _ui.update { it.copy(conversations = convs, pending = a.approvals("pending")) }
        runCatching { a.character() }.getOrNull()?.let { c -> _ui.update { it.copy(character = c) } }
        val cid = _ui.value.conversationId ?: convs.firstOrNull { it.id != NOTIFICATIONS_CONVERSATION }?.id
        if (cid != null) openConversation(cid) else newChat()
    }

    fun openConversation(cid: String) = launchSafe {
        val a = api ?: return@launchSafe
        val conv = _ui.value.conversations.firstOrNull { it.id == cid }
        val msgs = a.messages(cid)
        _ui.update {
            it.copy(
                conversationId = cid, messages = msgs, streaming = "", working = conv?.activeRun != null,
                status = if (conv?.activeRun != null) "Working on it…" else "", showLive = false,
                unreadNotifications = if (cid == NOTIFICATIONS_CONVERSATION) 0 else it.unreadNotifications,
            )
        }
    }

    fun deleteConversation(cid: String) = launchSafe {
        val a = api ?: return@launchSafe
        a.deleteConversation(cid)
        val rest = _ui.value.conversations.filterNot { it.id == cid }
        _ui.update { it.copy(conversations = rest) }
        if (_ui.value.conversationId == cid) {
            val next = rest.firstOrNull { it.id != NOTIFICATIONS_CONVERSATION }
            if (next != null) openConversation(next.id) else newChat()
        }
    }

    fun newChat() = launchSafe {
        val a = api ?: return@launchSafe
        val c = a.newConversation()
        _ui.update { it.copy(conversations = listOf(c) + it.conversations, conversationId = c.id, messages = emptyList(), streaming = "", working = false, status = "", showLive = false) }
    }

    fun refreshActivity() = launchSafe { api?.let { a -> _ui.update { it.copy(activity = a.activity(), pending = a.approvals("pending")) } } }
    fun refreshUpcoming() = launchSafe { api?.let { a -> _ui.update { it.copy(upcoming = a.upcoming()) } } }
    fun refreshMemory() = launchSafe { api?.let { a -> _ui.update { it.copy(memory = a.memory()) } } }

    // --- actions -------------------------------------------------------------------
    /** Upload a picked photo/file right away so sending is instant. Photos are shrunk to phone-friendly JPEGs first. */
    fun attach(name: String, bytes: ByteArray, mime: String) = launchSafe {
        val a = api ?: return@launchSafe
        val isImage = mime.startsWith("image/")
        val id = System.nanoTime()
        val (data, finalName, finalMime) = if (isImage) withContext(Dispatchers.Default) { shrinkPhoto(bytes, name) } else Triple(bytes, name, mime)
        val preview = if (isImage) withContext(Dispatchers.Default) { thumbnail(data) } else null
        _ui.update { it.copy(drafts = it.drafts + Draft(id, finalName, isImage, preview)) }
        val up = runCatching { a.upload(finalName, data, finalMime) }.getOrNull()
        _ui.update { s -> s.copy(drafts = s.drafts.map { if (it.id == id) it.copy(path = up?.path, failed = up == null) else it }) }
    }

    suspend fun speech(text: String): ByteArray? = api?.let { runCatching { it.tts(text) }.getOrNull() }
    fun refreshVoice() = launchSafe { api?.let { a -> _ui.update { it.copy(voice = a.voiceSettings()) } } }
    fun setVoice(id: String) = launchSafe { api?.let { a -> _ui.update { it.copy(voice = a.setVoice(id)) } } }

    fun removeDraft(id: Long) = _ui.update { s -> s.copy(drafts = s.drafts.filterNot { it.id == id }) }

    fun send(text: String) = send(text, voice = false)

    /** voice = sent from voice mode, so Clara answers in short spoken sentences. */
    fun send(text: String, voice: Boolean) = launchSafe {
        val a = api ?: return@launchSafe
        val cid = _ui.value.conversationId ?: a.newConversation().id.also { id -> _ui.update { it.copy(conversationId = id) } }
        val files = _ui.value.drafts.mapNotNull { it.path }
        val optimistic = Message("local-${System.nanoTime()}", cid, "user", text, attachments = files)
        _ui.update { it.copy(messages = it.messages + optimistic, working = true, status = if (files.isNotEmpty()) "Looking…" else "Thinking…", streaming = "", drafts = emptyList()) }
        val res = a.send(cid, text, files, voice)
        _ui.update { s -> s.copy(messages = s.messages.map { if (it.id == optimistic.id) res.message else it }) }
        if (_ui.value.messages.size <= 1) _ui.update { it.copy(conversations = a.conversations()) }
    }

    fun stop() = launchSafe { _ui.value.conversationId?.let { api?.stop(it) } }

    fun answer(approval: Approval, choice: String) = launchSafe {
        _ui.update { s -> s.copy(pending = s.pending.filterNot { it.id == approval.id }) }
        api?.answer(approval.id, choice)
    }

    fun jobAction(job: Job, action: String) = launchSafe {
        val a = api ?: return@launchSafe
        if (action == "delete") a.deleteJob(job.id) else a.jobAction(job.id, action)
        _ui.update { it.copy(upcoming = a.upcoming()) }
    }

    fun hideLive() = _ui.update { it.copy(showLive = false) }

    // --- goals, library, identity, screen (assistant sections) ------------------
    fun refreshGoals() = launchSafe { api?.let { a -> _ui.update { it.copy(goals = a.goals()) } } }
    fun addGoal(title: String, area: String) = launchSafe { api?.let { a -> a.addGoal(title, area); _ui.update { it.copy(goals = a.goals()) } } }
    fun toggleGoal(g: dev.clara.app.data.Goal) = launchSafe {
        _ui.update { s -> s.copy(goals = s.goals.map { if (it.id == g.id) it.copy(done = !g.done) else it }) }
        api?.setGoalDone(g.id, !g.done)
    }
    fun setCheckin(g: dev.clara.app.data.Goal, checkin: String, time: String, day: Int) = launchSafe {
        api?.let { a -> a.setCheckin(g.id, checkin, time, day); _ui.update { it.copy(goals = a.goals()) } }
    }
    suspend fun goalLog(g: dev.clara.app.data.Goal): List<dev.clara.app.data.GoalLogEntry> = api?.let { runCatching { it.goalLog(g.id) }.getOrNull() }.orEmpty()
    /** Ask Clara to check in on a goal (or send her daily note) right now; it arrives in the chat. */
    fun reachOutNow(kind: String, goalId: String? = null) = launchSafe {
        _ui.update { it.copy(status = "Writing…") }
        api?.proactiveNow(kind, goalId)
        _ui.update { it.copy(status = "") }
    }
    fun refreshProactive() = launchSafe { api?.let { a -> _ui.update { it.copy(proactive = a.proactive()) } } }
    fun setProactive(p: dev.clara.app.data.ProactiveSettings) = launchSafe { api?.let { a -> _ui.update { it.copy(proactive = a.setProactive(p)) } } }

    fun deleteGoal(g: dev.clara.app.data.Goal) = launchSafe { api?.let { a -> a.deleteGoal(g.id); _ui.update { it.copy(goals = a.goals()) } } }

    fun refreshLibrary() = launchSafe { api?.let { a -> _ui.update { it.copy(library = a.library()) } } }
    suspend fun libraryBytes(path: String): ByteArray? = api?.let { it.bytes(it.libraryUrl(path)) }

    // --- passwords: stored only on this phone; the PC gets names/sites/usernames ---------
    private fun localIndex() = ClaraHub.vault.logins().map { dev.clara.app.data.SavedLogin(it.name, it.site, it.username) }
    fun refreshLogins() = launchSafe {
        val idx = withContext(Dispatchers.Default) { localIndex() }
        _ui.update { it.copy(logins = idx) }
        api?.setVaultIndex(idx)
        api?.let { a -> _ui.update { it.copy(vaultRequests = a.vaultRequests()) } }
    }
    fun saveLogin(name: String, url: String, username: String, password: String) = launchSafe {
        withContext(Dispatchers.Default) { ClaraHub.vault.save(dev.clara.app.vault.PhoneLogin(name, url, username, password)) }
        refreshLogins()
    }
    fun deleteLogin(name: String) = launchSafe {
        withContext(Dispatchers.Default) { ClaraHub.vault.delete(name) }
        refreshLogins()
    }
    /** Called only after the fingerprint/PIN check succeeded (or with approve=false to deny). */
    fun answerVault(r: dev.clara.app.data.VaultRequest, approve: Boolean) = launchSafe {
        _ui.update { s -> s.copy(vaultRequests = s.vaultRequests.filterNot { it.id == r.id }) }
        val sealed = if (approve) withContext(Dispatchers.Default) { ClaraHub.vault.seal(r.id, r.name, r.pubkey) } else null
        api?.answerVault(r.id, sealed)
    }

    // --- API keys: stored encrypted on the PC in your account; never sent back to any phone -----
    fun refreshApis() = launchSafe { api?.let { a -> _ui.update { it.copy(apis = a.apis(), apiRequests = a.apiRequests()) } } }
    fun saveApi(name: String, baseUrl: String, authType: String, authName: String, key: String, notes: String, writePolicy: String) = launchSafe {
        api?.let { a -> a.saveApi(name, baseUrl, authType, authName, key, notes, writePolicy); _ui.update { it.copy(apis = a.apis()) } }
    }
    fun deleteApi(name: String) = launchSafe { api?.let { a -> a.deleteApi(name); _ui.update { it.copy(apis = a.apis()) } } }
    fun answerApi(r: dev.clara.app.data.ApiRequest, choice: String) = launchSafe {
        _ui.update { s -> s.copy(apiRequests = s.apiRequests.filterNot { it.id == r.id }) }
        api?.answerApi(r.id, choice)
    }

    // --- cloud boost ------------------------------------------------------------------
    fun refreshCloud() = launchSafe {
        api?.let { a -> val c = a.cloud(); _ui.update { it.copy(cloud = c, cloudRequests = c.requests, budgetSuggestions = c.suggestions) } }
    }
    fun refreshCharacter() = launchSafe { api?.let { a -> _ui.update { it.copy(character = a.character()) } } }
    fun setCharacterPreset(name: String) = launchSafe { api?.let { a -> _ui.update { it.copy(character = a.setCharacterPreset(name)) } } }
    fun setCharacterStyle(style: dev.clara.app.ui.components.CharacterStyle) = launchSafe {
        api?.let { a -> _ui.update { it.copy(character = a.setCharacterStyle(style)) } }
    }
    fun undoCharacter() = launchSafe { api?.let { a -> _ui.update { it.copy(character = a.undoCharacter()) } } }

    fun refreshConnectors() = launchSafe { api?.let { a -> _ui.update { it.copy(connectors = a.connectors()) } } }
    fun setConnectorClient(p: String, id: String, secret: String) = launchSafe {
        api?.let { a -> a.setConnectorClient(p, id.trim(), secret.trim()); _ui.update { it.copy(connectors = a.connectors()) } }
    }
    fun setConnectorToken(p: String, fields: Map<String, String>) = launchSafe {
        api?.let { a -> a.setConnectorToken(p, fields); _ui.update { it.copy(connectors = a.connectors()) } }
    }
    fun disconnect(p: String, forgetClient: Boolean) = launchSafe { api?.let { a -> a.disconnect(p, forgetClient); _ui.update { it.copy(connectors = a.connectors()) } } }
    fun setConnectorPolicy(p: String, key: String, value: String) = launchSafe {
        api?.let { a -> a.setConnectorPolicy(p, key, value); _ui.update { it.copy(connectors = a.connectors()) } }
    }

    /** Sign in with Google in the phone's browser; the redirect comes back to 127.0.0.1 on this phone (see LoopbackReceiver). */
    fun connect(p: String, openBrowser: (String) -> Boolean) = viewModelScope.launch {
        val a = api ?: return@launch
        val port = _ui.value.connectors.firstOrNull { it.provider == p }?.redirect?.substringAfterLast(':')?.substringBefore('/')?.toIntOrNull() ?: 53682
        val receiver = try { dev.clara.app.connect.LoopbackReceiver(port) } catch (e: Exception) {
            _ui.update { it.copy(error = "Couldn't start sign-in (port $port busy). Close other sign-ins and try again.") }; return@launch
        }
        try {
            _ui.update { it.copy(connectBusy = true, connectLink = null) }
            val url = a.startConnect(p, receiver.redirectUri)
            _ui.update { it.copy(connectLink = url) }
            if (!openBrowser(url)) _ui.update { it.copy(error = "No browser found. Copy the link below into a browser on this phone.") }
            val result = receiver.await()   // up to 10 minutes
            if (result.error != null) _ui.update { it.copy(error = "Google sign-in: ${result.error}") }
            else { a.finishConnect(p, result.state!!, result.code!!); _ui.update { it.copy(connectors = a.connectors()) } }
        } catch (e: Exception) {
            _ui.update { it.copy(error = e.message ?: e.toString()) }
        } finally {
            receiver.close()
            _ui.update { it.copy(connectBusy = false, connectLink = null) }
        }
    }

    fun refreshSpend() = launchSafe { api?.let { a -> _ui.update { it.copy(spend = a.spend()) } } }
    /** Caps only the user can set. null = leave as is; clear = remove the cap. */
    fun setCaps(daily: Double?, clearDaily: Boolean, monthly: Double?, clearMonthly: Boolean) = launchSafe {
        val o = kotlinx.serialization.json.buildJsonObject {
            daily?.let { put("cloud_daily_cap", kotlinx.serialization.json.JsonPrimitive(it)) }
            if (clearDaily) put("clear_cap", kotlinx.serialization.json.JsonPrimitive(true))
            monthly?.let { put("cloud_monthly_cap", kotlinx.serialization.json.JsonPrimitive(it)) }
            if (clearMonthly) put("clear_monthly_cap", kotlinx.serialization.json.JsonPrimitive(true))
        }
        api?.let { a -> a.updateCloud(o.toString()); refreshCloud(); _ui.update { it.copy(spend = a.spend()) } }
    }

    fun refreshBrand() = launchSafe { api?.let { a -> _ui.update { it.copy(brand = a.brand()) } } }
    fun saveBrand(b: dev.clara.app.data.BrandKit) = launchSafe { api?.let { a -> _ui.update { it.copy(brand = a.setBrand(b)) } } }
    fun setBrandLogo(bytes: ByteArray) = launchSafe {
        api?.let { a -> val b = a.setBrandLogo(bytes); _ui.update { it.copy(brand = b, brandLogoVersion = it.brandLogoVersion + 1) } }
    }
    fun removeBrandLogo() = launchSafe { api?.let { a -> val b = a.removeBrandLogo(); _ui.update { it.copy(brand = b, brandLogoVersion = it.brandLogoVersion + 1) } } }

    fun refreshVideoModels() = launchSafe { api?.let { a -> _ui.update { it.copy(videoModels = a.videoModels()) } } }
    fun setVideoModel(id: String) = launchSafe {
        api?.let { a -> a.updateCloud(kotlinx.serialization.json.buildJsonObject { put("cloud_video_model", kotlinx.serialization.json.JsonPrimitive(id)) }.toString()); refreshCloud() }
    }

    fun updateCloud(agentModel: String? = null, imageModel: String? = null, cap: Double? = null, clearCap: Boolean = false, always: Boolean? = null) = launchSafe {
        val o = kotlinx.serialization.json.buildJsonObject {
            agentModel?.let { put("cloud_agent_model", kotlinx.serialization.json.JsonPrimitive(it)) }
            imageModel?.let { put("cloud_image_model", kotlinx.serialization.json.JsonPrimitive(it)) }
            cap?.let { put("cloud_daily_cap", kotlinx.serialization.json.JsonPrimitive(it)) }
            if (clearCap) put("clear_cap", kotlinx.serialization.json.JsonPrimitive(true))
            always?.let { put("cloud_always", kotlinx.serialization.json.JsonPrimitive(it)) }
        }
        api?.let { a -> a.updateCloud(o.toString()); refreshCloud() }
    }
    fun setOpenRouterKey(key: String) = launchSafe {
        api?.let { a -> a.saveApi("openrouter", "https://openrouter.ai/api/v1", "bearer", "", key.trim(), "OpenRouter: cloud models and images for Clara", "trust"); refreshCloud() }
    }
    fun answerCloud(r: dev.clara.app.data.CloudRequest, choice: String) = launchSafe {
        _ui.update { s -> s.copy(cloudRequests = s.cloudRequests.filterNot { it.id == r.id }) }
        api?.answerCloud(r.id, choice)
    }
    fun answerBudget(b: dev.clara.app.data.BudgetSuggestion, accept: Boolean) = launchSafe {
        _ui.update { s -> s.copy(budgetSuggestions = s.budgetSuggestions.filterNot { it.id == b.id }) }
        api?.answerBudget(b.id, accept); refreshCloud()
    }

    fun refreshIdentity() = launchSafe { api?.let { a -> _ui.update { it.copy(identity = a.identity()) } } }
    fun saveIdentity(name: String, text: String) = launchSafe { api?.let { a -> a.setIdentity(name, text); _ui.update { it.copy(identity = a.identity()) } } }

    /** Screen tab: fetch the latest view of Clara's browser without touching the chat. */
    fun refreshScreen() = viewModelScope.launch {
        val a = api ?: return@launch
        val bytes = runCatching { a.bytes(a.screenshotUrl()) }.getOrNull() ?: return@launch
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap() ?: return@launch
        _ui.update { it.copy(screenshot = bmp, screenAt = System.currentTimeMillis()) }
    }

    private fun loadScreenshot() = viewModelScope.launch {
        val a = api ?: return@launch
        val bmp = withContext(Dispatchers.IO) {
            runCatching {
                a.http.newCall(Request.Builder().url(a.screenshotUrl()).build()).execute().use { r ->
                    if (!r.isSuccessful) null else BitmapFactory.decodeStream(r.body.byteStream())?.asImageBitmap()
                }
            }.getOrNull()
        }
        if (bmp != null) _ui.update { it.copy(screenshot = bmp, showLive = true) }
    }

    // --- live events -----------------------------------------------------------------
    private fun onEvent(ev: ClaraEvent) {
        val cur = _ui.value.conversationId
        when (ev) {
            is ClaraEvent.Routed -> if (ev.conversationId == cur) _ui.update {
                it.copy(working = true, status = when (ev.route) { "chat" -> "Typing…"; "schedule" -> "Scheduling…"; else -> "Working on it…" })
            }
            is ClaraEvent.Delta -> if (ev.conversationId == cur) _ui.update { it.copy(streaming = it.streaming + ev.text) }
            is ClaraEvent.RunStarted -> _ui.update { s ->
                val convs = s.conversations.map { if (it.id == ev.conversationId) it.copy(activeRun = ev.runId) else it }
                if (ev.conversationId == cur) s.copy(working = true, conversations = convs) else s.copy(conversations = convs)
            }
            is ClaraEvent.Activity -> {
                if (ev.conversationId == cur && ev.kind == "tool.started") _ui.update { it.copy(status = friendlyTool(ev.tool)) }
                // cloud sub-agent steps arrive already phrased, e.g. "☁️ Qwen: running pytest"
                if (ev.conversationId == cur && ev.kind == "cloud.step" && ev.detail != null) _ui.update { it.copy(status = ev.detail) }
            }
            is ClaraEvent.ScreenshotAvailable -> if (ev.conversationId == cur) _ui.update { it.copy(showLive = true) }  // Clara opened her browser: offer the live view
            is ClaraEvent.ApprovalRequested -> _ui.update { s ->
                s.copy(pending = listOf(ev.approval) + s.pending.filterNot { it.id == ev.approval.id }, status = "Waiting for your OK…")
            }
            is ClaraEvent.ApprovalResolved -> refreshActivity()
            is ClaraEvent.VaultRequest -> _ui.update { s -> s.copy(vaultRequests = listOf(ev.request) + s.vaultRequests.filterNot { it.id == ev.request.id }, status = "Waiting for your OK…") }
            is ClaraEvent.ApiRequest -> _ui.update { s -> s.copy(apiRequests = listOf(ev.request) + s.apiRequests.filterNot { it.id == ev.request.id }, status = "Waiting for your OK…") }
            is ClaraEvent.ApiResolved -> _ui.update { s -> s.copy(apiRequests = s.apiRequests.filterNot { it.id == ev.id }) }
            is ClaraEvent.CloudRequest -> _ui.update { s -> s.copy(cloudRequests = listOf(ev.request) + s.cloudRequests.filterNot { it.id == ev.request.id }, status = "Waiting for your OK…") }
            is ClaraEvent.CloudResolved -> _ui.update { s -> s.copy(cloudRequests = s.cloudRequests.filterNot { it.id == ev.id }) }
            is ClaraEvent.BudgetSuggestion -> _ui.update { s -> s.copy(budgetSuggestions = listOf(ev.suggestion) + s.budgetSuggestions.filterNot { it.id == ev.suggestion.id }) }
            is ClaraEvent.BudgetResolved -> _ui.update { s -> s.copy(budgetSuggestions = s.budgetSuggestions.filterNot { it.id == ev.id }) }
            is ClaraEvent.VaultResolved -> _ui.update { s -> s.copy(vaultRequests = s.vaultRequests.filterNot { it.id == ev.id }) }
            is ClaraEvent.Completed -> _ui.update { s ->
                val convs = s.conversations.map { if (it.id == ev.message.conversationId) it.copy(activeRun = null) else it }
                if (ev.message.conversationId != cur) s.copy(conversations = convs, unreadNotifications = s.unreadNotifications + 1)
                else s.copy(conversations = convs, messages = s.messages + ev.message, streaming = "", working = false, status = "", showLive = false,
                    doneAt = System.currentTimeMillis(), pending = s.pending.filterNot { it.runId != null && it.runId == ev.message.runId })
            }
            is ClaraEvent.CharacterChanged -> {
                _ui.update { s -> s.copy(character = s.character.copy(style = ev.style, canUndo = true)) }
                refreshCharacter()
            }
            is ClaraEvent.Notification -> _ui.update { s ->
                if (ev.message.conversationId == cur) s.copy(messages = s.messages + ev.message, doneAt = System.currentTimeMillis())
                else s.copy(unreadNotifications = s.unreadNotifications + 1)
            }
            else -> {}
        }
    }
}

fun friendlyTool(tool: String?): String = when {
    tool == null -> "Working on it…"
    tool == "terminal" || tool == "process" -> "Using the terminal…"
    tool == "web_search" -> "Searching the web…"
    tool == "web_extract" -> "Reading a page…"
    tool == "browser_vision" -> "Looking at the screen…"
    tool == "vision_analyze" -> "Studying the image…"
    tool.startsWith("browser") -> "Using the browser…"
    tool == "cronjob" -> "Scheduling…"
    tool == "write_file" || tool == "patch" -> "Writing a file…"
    tool == "read_file" || tool == "search_files" -> "Looking through files…"
    tool == "memory" -> "Remembering…"
    tool == "execute_code" -> "Running code…"
    tool == "delegate_task" -> "Getting a helper on it…"
    tool == "session_search" -> "Checking past chats…"
    tool == "todo" -> "Planning…"
    else -> "Working on it…"
}

/** The character's mood for the current conversation. */
fun moodOf(s: UiState, celebrating: Boolean = false): Mood {
    if (s.link == Link.Offline) return Mood.Sleeping
    if (s.pending.any { it.conversationId == s.conversationId } || s.vaultRequests.isNotEmpty() || s.apiRequests.isNotEmpty() || s.cloudRequests.isNotEmpty()) return Mood.Waiting
    if (s.working) {
        if (s.streaming.isNotBlank()) return Mood.Talking
        return when (s.status) {
            "Searching the web…" -> Mood.Searching
            "Using the browser…", "Reading a page…", "Looking at the screen…" -> Mood.Browsing
            "Scheduling…" -> Mood.Scheduling
            "Thinking…", "Typing…", "Checking past chats…", "Planning…", "Remembering…", "Studying the image…", "Looking…" -> Mood.Thinking
            else -> Mood.Working
        }
    }
    if (celebrating) return Mood.Done
    return Mood.Idle
}


private const val MAX_PHOTO_SIDE = 1600

/** Phone photos are 4000px+; Clara's vision works on far less. Returns (jpeg bytes, name.jpg, mime). */
fun shrinkPhoto(bytes: ByteArray, name: String): Triple<ByteArray, String, String> {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    if (bounds.outWidth <= 0) return Triple(bytes, name, "application/octet-stream")
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_PHOTO_SIDE) sample *= 2
    var bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
        ?: return Triple(bytes, name, "application/octet-stream")
    val side = maxOf(bmp.width, bmp.height)
    if (side > MAX_PHOTO_SIDE) {
        val k = MAX_PHOTO_SIDE.toFloat() / side
        bmp = android.graphics.Bitmap.createScaledBitmap(bmp, (bmp.width * k).toInt(), (bmp.height * k).toInt(), true)
    }
    bmp = rotateByExif(bytes, bmp)
    val out = java.io.ByteArrayOutputStream()
    bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 85, out)
    return Triple(out.toByteArray(), name.substringBeforeLast('.').ifBlank { "photo" } + ".jpg", "image/jpeg")
}

private fun rotateByExif(bytes: ByteArray, bmp: android.graphics.Bitmap): android.graphics.Bitmap {
    val deg = runCatching {
        when (androidx.exifinterface.media.ExifInterface(bytes.inputStream()).getAttributeInt(
            androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION, androidx.exifinterface.media.ExifInterface.ORIENTATION_NORMAL)) {
            androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
    }.getOrDefault(0f)
    if (deg == 0f) return bmp
    val m = android.graphics.Matrix().apply { postRotate(deg) }
    return android.graphics.Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
}

private fun thumbnail(bytes: ByteArray): androidx.compose.ui.graphics.ImageBitmap? =
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = 4 })?.asImageBitmap()
