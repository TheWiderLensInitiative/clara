package info.thewiderlens.clara.ui

import android.graphics.BitmapFactory
import android.os.Build
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import info.thewiderlens.clara.ClaraHub
import info.thewiderlens.clara.Link
import info.thewiderlens.clara.data.ActivityItem
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.data.BridgeApi
import info.thewiderlens.clara.data.ClaraEvent
import info.thewiderlens.clara.data.Conversation
import info.thewiderlens.clara.data.Job
import info.thewiderlens.clara.data.Memory
import info.thewiderlens.clara.data.Message
import info.thewiderlens.clara.ui.components.Mood
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
    val retryText: String = "",
    val voice: info.thewiderlens.clara.data.VoiceSettings = info.thewiderlens.clara.data.VoiceSettings(),
    val proactive: info.thewiderlens.clara.data.ProactiveSettings = info.thewiderlens.clara.data.ProactiveSettings(),
    val videoModels: List<info.thewiderlens.clara.data.VideoModel> = emptyList(),
    val brand: info.thewiderlens.clara.data.BrandKit = info.thewiderlens.clara.data.BrandKit(),
    val spend: info.thewiderlens.clara.data.SpendSummary? = null,
    val connectors: List<info.thewiderlens.clara.data.Connector> = emptyList(),
    val character: info.thewiderlens.clara.data.CharacterView = info.thewiderlens.clara.data.CharacterView(),
    val connectLink: String? = null,       // sign-in link while waiting for the browser to come back
    val connectBusy: Boolean = false,
    val deviceCode: Pair<String, info.thewiderlens.clara.data.DeviceCode>? = null,   // provider + code while a device sign-in waits
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
    val stopping: Boolean = false,           // Stop was tapped; Clara finishes the step in progress first
    val status: String = "",                 // "Searching the web…"
    val pending: List<Approval> = emptyList(),
    val activity: List<ActivityItem> = emptyList(),
    val upcoming: List<Job> = emptyList(),
    val memory: Memory = Memory(),
    val screenshot: ImageBitmap? = null,
    val showLive: Boolean = false,
    val help: info.thewiderlens.clara.data.HelpRequest? = null,   // Clara needs the user in her browser
    val unreadNotifications: Int = 0,
    val error: String? = null,
    val busyPairing: Boolean = false,
    val doneAt: Long = 0L,
    val goals: List<info.thewiderlens.clara.data.Goal> = emptyList(),
    val library: List<info.thewiderlens.clara.data.LibraryFile> = emptyList(),
    val recipes: List<info.thewiderlens.clara.data.RecipeView> = emptyList(),
    val purchases: List<info.thewiderlens.clara.data.PurchaseView>? = null,
    val identity: info.thewiderlens.clara.data.Identity = info.thewiderlens.clara.data.Identity(),
    val screenAt: Long = 0L,
    val logins: List<info.thewiderlens.clara.data.SavedLogin> = emptyList(),
    val vaultRequests: List<info.thewiderlens.clara.data.VaultRequest> = emptyList(),
    val apis: List<info.thewiderlens.clara.data.ApiService> = emptyList(),
    val apiRequests: List<info.thewiderlens.clara.data.ApiRequest> = emptyList(),
    val cloud: info.thewiderlens.clara.data.CloudState = info.thewiderlens.clara.data.CloudState(),
    val cloudRequests: List<info.thewiderlens.clara.data.CloudRequest> = emptyList(),
    val budgetSuggestions: List<info.thewiderlens.clara.data.BudgetSuggestion> = emptyList(),
)

class ClaraViewModel : ViewModel() {
    private val _ui = MutableStateFlow(UiState())
    val ui: StateFlow<UiState> = _ui

    private var api: BridgeApi? = null
    private var pendingConversation: String? = null
    private var activityVersion = 0L
    private var loadGeneration = 0L
    private var refreshJob: kotlinx.coroutines.Job? = null

    init {
        viewModelScope.launch {
            ClaraHub.api.collect { a ->
                api = a
                _ui.update { it.copy(paired = a != null, bridgeUrl = a?.baseUrl ?: it.bridgeUrl) }
                if (a != null) { refreshAll(); refreshLogins(); refreshApis(); refreshCloud() }
            }
        }
        viewModelScope.launch { ClaraHub.link.collect { l -> _ui.update { it.copy(link = l) }; if (l == Link.Online) refreshAllPending() } }
        viewModelScope.launch { ClaraHub.via.collect { v -> _ui.update { it.copy(via = v) } } }
        viewModelScope.launch { ClaraHub.currentPairing.collect { p -> _ui.update { it.copy(remoteUrl = p?.remoteUrl) } } }
        viewModelScope.launch { ClaraHub.api.collect { a -> if (a != null) _ui.update { it.copy(bridgeUrl = a.baseUrl) } } }
        viewModelScope.launch { ClaraHub.events.collect(::onEvent) }
    }

    private fun refreshAllPending() {
        refreshAll(); refreshApis(); refreshCloud()
        launchSafe { val a = api ?: return@launchSafe; val requests = a.vaultRequests(); _ui.update { it.copy(vaultRequests = requests) } }
    }

    private fun launchSafe(block: suspend () -> Unit) = viewModelScope.launch {
        try { block() } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) {
            // this phone was unpaired on the PC: go back to the pairing screen instead of failing every call
            if (e is info.thewiderlens.clara.data.BridgeException && e.code == 401) { confirmUnpaired(); return@launch }
            _ui.update { it.copy(error = e.message ?: e.toString()) }
        }
    }

    /** Only forget the pairing when the PC really says this phone was removed (checked twice, a moment apart). */
    private fun confirmUnpaired() = viewModelScope.launch {
        repeat(2) {
            kotlinx.coroutines.delay(1500)
            val stillBad = try { api?.conversations(); false } catch (e: info.thewiderlens.clara.data.BridgeException) { e.code == 401 } catch (_: Exception) { false }
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
    fun refreshAll() {
        if (refreshJob?.isActive == true) return
        refreshJob = launchSafe {
        val a = api ?: return@launchSafe
        val convs = a.conversations()
        run { val fetched0 = a.approvals("pending"); _ui.update { it.copy(conversations = convs, pending = fetched0) } }
        runCatching { a.character() }.getOrNull()?.let { c -> _ui.update { it.copy(character = c) } }
        runCatching { a.openHelp() }.onSuccess { h -> _ui.update { it.copy(help = h) } }
        val cid = pendingConversation ?: _ui.value.conversationId ?: convs.firstOrNull { it.id != NOTIFICATIONS_CONVERSATION }?.id
        if (cid != null) openConversation(cid) else newChat()
        }
    }

    fun openConversation(cid: String): kotlinx.coroutines.Job {
        pendingConversation = cid
        val generation = ++loadGeneration
        return launchSafe {
        val a = api ?: return@launchSafe
        if (_ui.value.conversationId != cid) _ui.update { it.copy(conversationId = cid, messages = emptyList(), streaming = "") }
        val activityAtLoad = activityVersion
        val initialIds = _ui.value.messages.map { it.id }.toSet()
        val msgs = a.messages(cid)
        if (generation != loadGeneration || api !== a) return@launchSafe
        pendingConversation = null
        val conv = _ui.value.conversations.firstOrNull { it.id == cid }
        _ui.update {
            val arrived = it.messages.filter { m -> m.id !in initialIds }
            val working = if (activityVersion != activityAtLoad) it.working else conv?.activeRun != null
            it.copy(
                conversationId = cid, messages = (msgs + arrived).distinctBy { m -> m.id }, working = working,
                stopping = if (activityVersion != activityAtLoad) it.stopping else false,
                status = if (activityVersion != activityAtLoad) it.status else if (working) "Working on it…" else "", showLive = false,
                unreadNotifications = if (cid == NOTIFICATIONS_CONVERSATION) 0 else it.unreadNotifications,
            )
        }
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
        val generation = ++loadGeneration
        pendingConversation = null
        val a = api ?: return@launchSafe
        val c = a.newConversation()
        if (generation != loadGeneration) return@launchSafe
        _ui.update { it.copy(conversations = listOf(c) + it.conversations, conversationId = c.id, messages = emptyList(), streaming = "", working = false, stopping = false, status = "", showLive = false) }
    }

    fun refreshActivity() = launchSafe { api?.let { a -> run { val fetched0 = a.activity(); val fetched1 = a.approvals("pending"); _ui.update { it.copy(activity = fetched0, pending = fetched1) } } } }
    fun refreshUpcoming() = launchSafe { api?.let { a -> run { val fetched0 = a.upcoming(); _ui.update { it.copy(upcoming = fetched0) } } } }
    fun refreshMemory() = launchSafe { api?.let { a -> run { val fetched0 = a.memory(); _ui.update { it.copy(memory = fetched0) } } } }

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
    fun refreshVoice() = launchSafe { api?.let { a -> run { val fetched0 = a.voiceSettings(); _ui.update { it.copy(voice = fetched0) } } } }
    fun setVoice(id: String) = launchSafe { api?.let { a -> run { val fetched0 = a.setVoice(id); _ui.update { it.copy(voice = fetched0) } } } }

    fun removeDraft(id: Long) = _ui.update { s -> s.copy(drafts = s.drafts.filterNot { it.id == id }) }

    fun send(text: String) = send(text, voice = false)

    /** voice = sent from voice mode, so Clara answers in short spoken sentences. */
    fun send(text: String, voice: Boolean) = launchSafe {
        val initialConversation = _ui.value.conversationId
        try {
        val a = api ?: throw IllegalStateException("Clara is not connected yet. Your message is saved below.")
        val cid = _ui.value.conversationId ?: a.newConversation().id.also { id -> _ui.update { it.copy(conversationId = id) } }
        if (_ui.value.working) return@launchSafe
        val savedDrafts = _ui.value.drafts
        if (savedDrafts.any { it.path == null || it.failed }) throw IllegalStateException("Wait for attachments to finish uploading or remove failed attachments.")
        val files = savedDrafts.mapNotNull { it.path }
        activityVersion++
        val optimistic = Message("local-${System.nanoTime()}", cid, "user", text, attachments = files)
        _ui.update { it.copy(messages = it.messages + optimistic, working = true, status = if (files.isNotEmpty()) "Looking…" else "Thinking…", streaming = "", drafts = emptyList(), retryText = "") }
        try {
            val res = a.send(cid, text, files, voice)
            _ui.update { s -> if (s.conversationId != cid) s else s.copy(messages = s.messages.map { if (it.id == optimistic.id) res.message else it }) }
        } catch (e: Exception) {
            _ui.update { s -> if (s.conversationId != cid) s else s.copy(
                messages = s.messages.filterNot { it.id == optimistic.id }, working = false, status = "", retryText = text,
                drafts = (savedDrafts + s.drafts).distinctBy { it.id }) }
            throw e
        }
        if (_ui.value.messages.size <= 1) run { val fetched0 = a.conversations(); _ui.update { it.copy(conversations = fetched0) } }
        } catch (error: Exception) {
            if (error !is kotlinx.coroutines.CancellationException) _ui.update { state ->
                if (state.conversationId == initialConversation || initialConversation == null)
                    state.copy(retryText = text) else state
            }
            throw error
        }
    }

    fun stop() = launchSafe {
        val cid = _ui.value.conversationId ?: return@launchSafe
        if (_ui.value.stopping) return@launchSafe   // one tap is enough; she stops after the current step
        _ui.update { it.copy(stopping = true, status = "Stopping…") }
        try {
            api?.stop(cid)
        } catch (error: Exception) {
            _ui.update { it.copy(stopping = false, status = if (it.working) "Working on it…" else "") }
            throw error
        }
    }

    fun answer(approval: Approval, choice: String) = launchSafe {
        val a = api ?: return@launchSafe
        a.answer(approval.id, choice)
        _ui.update { s -> s.copy(pending = s.pending.filterNot { it.id == approval.id }) }
    }

    fun jobAction(job: Job, action: String) = launchSafe {
        val a = api ?: return@launchSafe
        if (action == "delete") a.deleteJob(job.id) else a.jobAction(job.id, action)
        run { val fetched0 = a.upcoming(); _ui.update { it.copy(upcoming = fetched0) } }
    }

    fun hideLive() = _ui.update { it.copy(showLive = false) }

    // --- goals, library, identity, screen (assistant sections) ------------------
    fun refreshGoals() = launchSafe { api?.let { a -> run { val fetched0 = a.goals(); _ui.update { it.copy(goals = fetched0) } } } }
    fun addGoal(title: String, area: String) = launchSafe { api?.let { a -> a.addGoal(title, area); run { val fetched0 = a.goals(); _ui.update { it.copy(goals = fetched0) } } } }
    fun toggleGoal(g: info.thewiderlens.clara.data.Goal) = launchSafe {
        _ui.update { s -> s.copy(goals = s.goals.map { if (it.id == g.id) it.copy(done = !g.done) else it }) }
        api?.setGoalDone(g.id, !g.done)
    }
    fun setCheckin(g: info.thewiderlens.clara.data.Goal, checkin: String, time: String, day: Int) = launchSafe {
        api?.let { a -> a.setCheckin(g.id, checkin, time, day); run { val fetched0 = a.goals(); _ui.update { it.copy(goals = fetched0) } } }
    }
    suspend fun goalLog(g: info.thewiderlens.clara.data.Goal): List<info.thewiderlens.clara.data.GoalLogEntry> = api?.let { runCatching { it.goalLog(g.id) }.getOrNull() }.orEmpty()
    /** Ask Clara to check in on a goal (or send her daily note) right now; it arrives in the chat. */
    fun reachOutNow(kind: String, goalId: String? = null) = launchSafe {
        _ui.update { it.copy(status = "Writing…") }
        api?.proactiveNow(kind, goalId)
        _ui.update { it.copy(status = "") }
    }
    fun refreshProactive() = launchSafe { api?.let { a -> run { val fetched0 = a.proactive(); _ui.update { it.copy(proactive = fetched0) } } } }
    fun setProactive(p: info.thewiderlens.clara.data.ProactiveSettings) = launchSafe { api?.let { a -> run { val fetched0 = a.setProactive(p); _ui.update { it.copy(proactive = fetched0) } } } }

    fun deleteGoal(g: info.thewiderlens.clara.data.Goal) = launchSafe { api?.let { a -> a.deleteGoal(g.id); run { val fetched0 = a.goals(); _ui.update { it.copy(goals = fetched0) } } } }

    fun refreshRecipes() = launchSafe { api?.let { a -> val fetched = a.recipes(); _ui.update { it.copy(recipes = fetched) } } }
    fun deleteRecipe(name: String) = launchSafe { api?.let { a -> a.deleteRecipe(name); val fetched = a.recipes(); _ui.update { it.copy(recipes = fetched) } } }
    fun refreshPurchases() = launchSafe { api?.let { a -> val fetched = a.purchases(); _ui.update { it.copy(purchases = fetched) } } }
    fun deletePurchase(id: String) = launchSafe { api?.let { a -> a.deletePurchase(id); val fetched = a.purchases(); _ui.update { it.copy(purchases = fetched) } } }
    /** Buy again: a message in the open chat; the Bridge replays the saved playbook (same link and address, both approvals). */
    fun buyAgain(p: info.thewiderlens.clara.data.PurchaseView) = send("🔁 Buy again: ${p.title.take(80)} [${p.id}]")
    fun refreshLibrary() = launchSafe { api?.let { a -> run { val fetched0 = a.library(); _ui.update { it.copy(library = fetched0) } } } }
    suspend fun libraryBytes(path: String): ByteArray? = api?.let {
        it.bytes(if (path.startsWith("https://")) it.shopImageUrl(path) else it.libraryUrl(path))   // product photos come through the PC
    }
    fun deleteLibraryFile(path: String) = launchSafe { api?.let { a -> a.deleteLibraryFile(path); val fetched = a.library(); _ui.update { it.copy(library = fetched) } } }
    fun saveLibraryFile(path: String, text: String) = launchSafe { api?.let { a -> a.saveLibraryFile(path, text); val fetched = a.library(); _ui.update { it.copy(library = fetched) } } }

    // --- passwords: stored only on this phone; the PC gets names/sites/usernames ---------
    private fun localIndex() = ClaraHub.vault.logins().map { info.thewiderlens.clara.data.SavedLogin(it.name, it.site, it.username) }
    fun refreshLogins() = launchSafe {
        val idx = withContext(Dispatchers.Default) { localIndex() }
        _ui.update { it.copy(logins = idx) }
        api?.setVaultIndex(idx)
        api?.let { a -> run { val fetched0 = a.vaultRequests(); _ui.update { it.copy(vaultRequests = fetched0) } } }
    }
    fun saveLogin(name: String, url: String, username: String, password: String) = launchSafe {
        withContext(Dispatchers.Default) { ClaraHub.vault.save(info.thewiderlens.clara.vault.PhoneLogin(name, url, username, password)) }
        refreshLogins()
    }
    fun deleteLogin(name: String) = launchSafe {
        withContext(Dispatchers.Default) { ClaraHub.vault.delete(name) }
        refreshLogins()
    }
    /** Called only after the fingerprint/PIN check succeeded (or with approve=false to deny). */
    fun answerVault(r: info.thewiderlens.clara.data.VaultRequest, approve: Boolean) = launchSafe {
        val a = api ?: return@launchSafe
        val sealed = if (approve) withContext(Dispatchers.Default) { ClaraHub.vault.seal(r.id, r.name, r.pubkey) } else null
        a.answerVault(r.id, sealed)
        _ui.update { s -> s.copy(vaultRequests = s.vaultRequests.filterNot { it.id == r.id }) }
    }

    // --- API keys: stored encrypted on the PC in your account; never sent back to any phone -----
    fun refreshApis() = launchSafe { api?.let { a -> run { val fetched0 = a.apis(); val fetched1 = a.apiRequests(); _ui.update { it.copy(apis = fetched0, apiRequests = fetched1) } } } }
    fun saveApi(name: String, baseUrl: String, authType: String, authName: String, key: String, notes: String, writePolicy: String) = launchSafe {
        api?.let { a -> a.saveApi(name, baseUrl, authType, authName, key, notes, writePolicy); run { val fetched0 = a.apis(); _ui.update { it.copy(apis = fetched0) } } }
    }
    fun deleteApi(name: String) = launchSafe { api?.let { a -> a.deleteApi(name); run { val fetched0 = a.apis(); _ui.update { it.copy(apis = fetched0) } } } }
    fun answerApi(r: info.thewiderlens.clara.data.ApiRequest, choice: String) = launchSafe {
        val a = api ?: return@launchSafe
        a.answerApi(r.id, choice)
        _ui.update { s -> s.copy(apiRequests = s.apiRequests.filterNot { it.id == r.id }) }
    }

    // --- cloud boost ------------------------------------------------------------------
    fun refreshCloud() = launchSafe {
        api?.let { a -> val c = a.cloud(); _ui.update { it.copy(cloud = c, cloudRequests = c.requests, budgetSuggestions = c.suggestions) } }
    }
    fun refreshCharacter() = launchSafe { api?.let { a -> run { val fetched0 = a.character(); _ui.update { it.copy(character = fetched0) } } } }
    fun setCharacterPreset(name: String) = launchSafe { api?.let { a -> run { val fetched0 = a.setCharacterPreset(name); _ui.update { it.copy(character = fetched0) } } } }
    fun setCharacterStyle(style: info.thewiderlens.clara.ui.components.CharacterStyle) = launchSafe {
        api?.let { a -> run { val fetched0 = a.setCharacterStyle(style); _ui.update { it.copy(character = fetched0) } } }
    }
    fun undoCharacter() = launchSafe { api?.let { a -> run { val fetched0 = a.undoCharacter(); _ui.update { it.copy(character = fetched0) } } } }

    fun refreshConnectors() = launchSafe { api?.let { a -> run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } } }
    fun setConnectorClient(p: String, id: String, secret: String) = launchSafe {
        api?.let { a -> a.setConnectorClient(p, id.trim(), secret.trim()); run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } }
    }
    fun setConnectorToken(p: String, fields: Map<String, String>) = launchSafe {
        api?.let { a -> a.setConnectorToken(p, fields); run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } }
    }
    fun disconnect(p: String, forgetClient: Boolean) = launchSafe { api?.let { a -> a.disconnect(p, forgetClient); run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } } }
    fun setConnectorPolicy(p: String, key: String, value: String) = launchSafe {
        api?.let { a -> a.setConnectorPolicy(p, key, value); run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } }
    }

    /** Sign in with Google in the phone's browser; the redirect comes back to 127.0.0.1 on this phone (see LoopbackReceiver). */
    fun connect(p: String, openBrowser: (String) -> Boolean) = viewModelScope.launch {
        val a = api ?: return@launch
        if (_ui.value.connectors.firstOrNull { it.provider == p }?.kind == "device") { connectDevice(a, p); return@launch }
        val port = _ui.value.connectors.firstOrNull { it.provider == p }?.redirect?.substringAfterLast(':')?.substringBefore('/')?.toIntOrNull() ?: 53682
        val receiver = try { info.thewiderlens.clara.connect.LoopbackReceiver(port) } catch (e: Exception) {
            _ui.update { it.copy(error = "Couldn't start sign-in (port $port busy). Close other sign-ins and try again.") }; return@launch
        }
        try {
            _ui.update { it.copy(connectBusy = true, connectLink = null) }
            // Slack only treats "localhost" as a desktop sign-in; the same loopback receiver answers either name
            val wantsLocalhost = _ui.value.connectors.firstOrNull { it.provider == p }?.redirect?.startsWith("http://localhost") == true
            val url = a.startConnect(p, if (wantsLocalhost) receiver.redirectUri.replace("127.0.0.1", "localhost") else receiver.redirectUri)
            _ui.update { it.copy(connectLink = url) }
            if (!openBrowser(url)) _ui.update { it.copy(error = "No browser found. Copy the link below into a browser on this phone.") }
            val result = receiver.await(android.net.Uri.parse(url).getQueryParameter("state"))   // up to 10 minutes
            if (result.error != null) _ui.update { it.copy(error = "Sign-in: ${result.error}") }
            else { a.finishConnect(p, result.state!!, result.code!!); run { val fetched0 = a.connectors(); _ui.update { it.copy(connectors = fetched0) } } }
        } catch (e: Exception) {
            _ui.update { it.copy(error = e.message ?: e.toString()) }
        } finally {
            receiver.close()
            _ui.update { it.copy(connectBusy = false, connectLink = null) }
        }
    }

    /** GitHub-style sign-in: show the code, then check until the Bridge reports the account connected (or it expires). */
    private suspend fun connectDevice(a: info.thewiderlens.clara.data.BridgeApi, p: String) {
        try {
            _ui.update { it.copy(connectBusy = true) }
            val code = a.startDevice(p)
            _ui.update { it.copy(deviceCode = p to code) }
            val until = System.currentTimeMillis() + code.expiresIn * 1000L
            while (System.currentTimeMillis() < until && _ui.value.deviceCode?.first == p) {
                kotlinx.coroutines.delay(4000)
                val fetched = runCatching { a.connectors() }.getOrNull() ?: continue
                _ui.update { it.copy(connectors = fetched) }
                if (fetched.firstOrNull { it.provider == p }?.connected == true) break
            }
        } catch (e: Exception) {
            _ui.update { it.copy(error = e.message ?: e.toString()) }
        } finally {
            _ui.update { it.copy(connectBusy = false, deviceCode = null) }
        }
    }

    fun cancelDeviceCode() = _ui.update { it.copy(deviceCode = null) }

    fun refreshSpend() = launchSafe { api?.let { a -> run { val fetched0 = a.spend(); _ui.update { it.copy(spend = fetched0) } } } }
    /** Caps only the user can set. null = leave as is; clear = remove the cap. */
    fun setCaps(daily: Double?, clearDaily: Boolean, monthly: Double?, clearMonthly: Boolean) = launchSafe {
        val o = kotlinx.serialization.json.buildJsonObject {
            daily?.let { put("cloud_daily_cap", kotlinx.serialization.json.JsonPrimitive(it)) }
            if (clearDaily) put("clear_cap", kotlinx.serialization.json.JsonPrimitive(true))
            monthly?.let { put("cloud_monthly_cap", kotlinx.serialization.json.JsonPrimitive(it)) }
            if (clearMonthly) put("clear_monthly_cap", kotlinx.serialization.json.JsonPrimitive(true))
        }
        api?.let { a -> a.updateCloud(o.toString()); refreshCloud(); run { val fetched0 = a.spend(); _ui.update { it.copy(spend = fetched0) } } }
    }

    fun refreshBrand() = launchSafe { api?.let { a -> run { val fetched0 = a.brand(); _ui.update { it.copy(brand = fetched0) } } } }
    fun saveBrand(b: info.thewiderlens.clara.data.BrandKit) = launchSafe { api?.let { a -> run { val fetched0 = a.setBrand(b); _ui.update { it.copy(brand = fetched0) } } } }
    fun setBrandLogo(bytes: ByteArray) = launchSafe {
        api?.let { a -> val b = a.setBrandLogo(bytes); _ui.update { it.copy(brand = b, brandLogoVersion = it.brandLogoVersion + 1) } }
    }
    fun removeBrandLogo() = launchSafe { api?.let { a -> val b = a.removeBrandLogo(); _ui.update { it.copy(brand = b, brandLogoVersion = it.brandLogoVersion + 1) } } }

    fun refreshVideoModels() = launchSafe { api?.let { a -> run { val fetched0 = a.videoModels(); _ui.update { it.copy(videoModels = fetched0) } } } }
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
    fun answerCloud(r: info.thewiderlens.clara.data.CloudRequest, choice: String) = launchSafe {
        val a = api ?: return@launchSafe
        a.answerCloud(r.id, choice)
        _ui.update { s -> s.copy(cloudRequests = s.cloudRequests.filterNot { it.id == r.id }) }
    }
    fun answerBudget(b: info.thewiderlens.clara.data.BudgetSuggestion, accept: Boolean) = launchSafe {
        val a = api ?: return@launchSafe
        a.answerBudget(b.id, accept)
        _ui.update { s -> s.copy(budgetSuggestions = s.budgetSuggestions.filterNot { it.id == b.id }) }
        refreshCloud()
    }

    fun refreshIdentity() = launchSafe { api?.let { a -> run { val fetched0 = a.identity(); _ui.update { it.copy(identity = fetched0) } } } }
    fun saveIdentity(name: String, text: String) = launchSafe { api?.let { a -> a.setIdentity(name, text); run { val fetched0 = a.identity(); _ui.update { it.copy(identity = fetched0) } } } }

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
        val affectsCurrent = when (ev) {
            is ClaraEvent.Routed -> ev.conversationId == cur
            is ClaraEvent.RunStarted -> ev.conversationId == cur
            is ClaraEvent.Completed -> ev.message.conversationId == cur
            else -> false
        }
        if (affectsCurrent) activityVersion++
        when (ev) {
            ClaraEvent.Resync -> refreshAllPending()
            is ClaraEvent.Routed -> if (ev.conversationId == cur) _ui.update {
                it.copy(working = true, status = when (ev.route) { "chat" -> "Typing…"; "schedule" -> "Scheduling…"; else -> "Working on it…" })
            }
            is ClaraEvent.Delta -> if (ev.conversationId == cur) _ui.update { it.copy(streaming = it.streaming + ev.text) }
            is ClaraEvent.RunStarted -> _ui.update { s ->
                val convs = s.conversations.map { if (it.id == ev.conversationId) it.copy(activeRun = ev.runId) else it }
                if (ev.conversationId == cur) s.copy(working = true, stopping = false, conversations = convs) else s.copy(conversations = convs)
            }
            is ClaraEvent.RunStopping -> if (ev.conversationId == cur) _ui.update { it.copy(stopping = true, status = "Stopping…") }
            is ClaraEvent.Activity -> if (!_ui.value.stopping) {
                if (ev.conversationId == cur && ev.kind == "tool.started") _ui.update { it.copy(status = friendlyTool(ev.tool)) }
                // Laya spotted a website task: show the browser card before Chrome is even up
                if (ev.conversationId == cur && ev.kind == "browser.opening") _ui.update { it.copy(working = true, status = "Opening my browser…") }
                // cloud sub-agent steps arrive already phrased, e.g. "☁️ Qwen: running pytest"
                if (ev.conversationId == cur && ev.kind == "cloud.step" && ev.detail != null) _ui.update { it.copy(status = ev.detail) }
                // each step of her browser, live: "🌐 Clicked “Save changes”"
                if (ev.conversationId == cur && ev.kind == "browser.step" && ev.detail != null) _ui.update { it.copy(status = BROWSER_STEP + ev.detail) }
            }
            is ClaraEvent.HelpRequested -> _ui.update { it.copy(help = ev.help, status = "Needs your help…") }
            is ClaraEvent.HelpResolved -> _ui.update { if (it.help?.id == ev.id) it.copy(help = null) else it }
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
                else s.copy(conversations = convs, messages = (s.messages + ev.message).distinctBy { it.id }, streaming = "", working = false, stopping = false, status = "", showLive = false,
                    doneAt = System.currentTimeMillis(), pending = s.pending.filterNot { it.runId != null && it.runId == ev.message.runId })
            }
            is ClaraEvent.CharacterChanged -> {
                _ui.update { s -> s.copy(character = s.character.copy(style = ev.style, canUndo = true)) }
                refreshCharacter()
            }
            is ClaraEvent.Notification -> _ui.update { s ->
                if (ev.message.conversationId == cur) s.copy(messages = (s.messages + ev.message).distinctBy { it.id }, doneAt = System.currentTimeMillis())
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

/** Prefix of a live browser step in the status line ("🌐 Clicked “Next”"). */
const val BROWSER_STEP = "🌐 "

/** The character's mood for the current conversation. */
fun moodOf(s: UiState, celebrating: Boolean = false): Mood {
    if (s.link == Link.Offline) return Mood.Sleeping
    if (s.help != null || s.pending.any { it.conversationId == s.conversationId } || s.vaultRequests.isNotEmpty() || s.apiRequests.isNotEmpty() || s.cloudRequests.isNotEmpty()) return Mood.Waiting
    if (s.working) {
        if (s.streaming.isNotBlank()) return Mood.Talking
        if (s.status.startsWith(BROWSER_STEP)) return Mood.Browsing   // a live browser step
        return when (s.status) {
            "Searching the web…", "Reading a page…" -> Mood.Searching   // web_extract fetches text: no browser to show
            "Opening my browser…", "Using the browser…", "Looking at the screen…" -> Mood.Browsing
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
