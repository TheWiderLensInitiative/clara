package info.thewiderlens.clara

import android.content.Context
import info.thewiderlens.clara.data.BridgeApi
import info.thewiderlens.clara.data.ClaraEvent
import info.thewiderlens.clara.data.Settings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

enum class Link { Offline, Connecting, Online }

/**
 * Process-wide owner of the Bridge connection. The foreground service keeps it alive;
 * the UI and notifications both read from [events].
 */
object ClaraHub {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null

    lateinit var settings: Settings
        private set
    lateinit var vault: info.thewiderlens.clara.vault.PhoneVault
        private set

    private val _api = MutableStateFlow<BridgeApi?>(null)
    val api: StateFlow<BridgeApi?> = _api

    private val _link = MutableStateFlow(Link.Offline)
    val link: StateFlow<Link> = _link

    private val _events = MutableSharedFlow<ClaraEvent>(extraBufferCapacity = 256)
    val events: SharedFlow<ClaraEvent> = _events

    /** How we're reaching the PC right now: "home" (Wi-Fi, fastest) or "remote" (Tailscale, from anywhere). */
    private val _via = MutableStateFlow<String?>(null)
    val via: StateFlow<String?> = _via

    private val pairing = MutableStateFlow<info.thewiderlens.clara.data.Pairing?>(null)
    val currentPairing: StateFlow<info.thewiderlens.clara.data.Pairing?> = pairing
    private val networkChanged = MutableSharedFlow<Unit>(extraBufferCapacity = 4)

    /** True while an Activity is visible; the service only notifies for chat replies when this is false. */
    @Volatile var appVisible = false

    fun init(context: Context) {
        if (::settings.isInitialized) return
        settings = Settings(context.applicationContext)
        vault = info.thewiderlens.clara.vault.PhoneVault(context.applicationContext)
        scope.launch {
            var token: String? = null
            settings.pairing.collect { p ->
                pairing.value = p
                // the UI treats "has an api" as "paired", so set one right away; the connection loop then picks the best address
                if (p == null) { _api.value = null; token = null }
                else if (p.token != token) { token = p.token; _api.value = BridgeApi(p.addresses.first(), p.token) }
            }
        }
        // phone switched networks (Wi-Fi <-> mobile data): reconnect right away instead of waiting on a dead connection
        runCatching {
            val cm = context.getSystemService(android.net.ConnectivityManager::class.java)
            cm.registerDefaultNetworkCallback(object : android.net.ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: android.net.Network) { networkChanged.tryEmit(Unit) }
                override fun onLost(network: android.net.Network) { networkChanged.tryEmit(Unit) }
            })
        }
    }

    private fun isRemote(url: String, p: info.thewiderlens.clara.data.Pairing) = url.startsWith("https://") || url == p.remoteUrl

    /** The best address that answers right now: home Wi-Fi first, then Tailscale. All are tried at once. */
    private suspend fun pick(p: info.thewiderlens.clara.data.Pairing): String? = kotlinx.coroutines.coroutineScope {
        val checks = p.addresses.map { a -> a to async { BridgeApi(a, p.token).reachable() } }
        try { checks.firstOrNull { (_, ok) -> ok.await() }?.first }
        finally { checks.forEach { (_, check) -> check.cancel() } }
    }

    fun start() {
        if (loop?.isActive == true) return
        loop = scope.launch {
            pairing.collectLatest { p ->
                if (p == null) { _api.value = null; _link.value = Link.Offline; _via.value = null; return@collectLatest }
                var backoff = 1_000L
                while (true) {
                    _link.value = Link.Connecting
                    val chosen = pick(p)
                    if (chosen == null) {   // PC off, or away from home without Tailscale
                        _link.value = Link.Offline
                        kotlinx.coroutines.withTimeoutOrNull(backoff) { networkChanged.first() }
                        backoff = (backoff * 2).coerceAtMost(30_000L)
                        continue
                    }
                    val api = _api.value?.takeIf { it.baseUrl == chosen } ?: BridgeApi(chosen, p.token).also { _api.value = it }
                    val remote = isRemote(chosen, p)
                    _via.value = if (remote) "remote" else "home"
                    // learn this PC's addresses (home Wi-Fi + Tailscale) so we can switch by ourselves later
                    runCatching { api.addresses() }.getOrNull()?.let { a ->
                        if (a.lan != p.lanUrl || a.remote != p.remoteUrl) scope.launch { settings.saveAddresses(a.lan, a.remote) }
                    }
                    val reason = kotlinx.coroutines.coroutineScope {
                        val stream = async {
                            api.events().collect { ev ->
                                when (ev) {
                                    ClaraEvent.Connected -> { _link.value = Link.Online; backoff = 1_000L }
                                    is ClaraEvent.Disconnected -> _link.value = Link.Offline
                                    else -> {}
                                }
                                _events.emit(ev)
                            }
                            "dropped"
                        }
                        val netChange = async { networkChanged.first(); kotlinx.coroutines.delay(1_500); "network" }
                        val backHome = async {
                            // on Tailscale: every minute, check whether home Wi-Fi works again (faster, stays on the LAN)
                            if (!remote) kotlinx.coroutines.awaitCancellation()
                            while (true) {
                                kotlinx.coroutines.delay(60_000)
                                val home = p.addresses.filter { !isRemote(it, p) }
                                if (home.any { BridgeApi(it, p.token).reachable() }) return@async "home"
                            }
                            @Suppress("UNREACHABLE_CODE") "home"
                        }
                        val first = kotlinx.coroutines.selects.select<String> {
                            stream.onAwait { it }; netChange.onAwait { it }; backHome.onAwait { it }
                        }
                        coroutineContext[Job]?.children?.forEach { it.cancel() }
                        first
                    }
                    if (reason == "dropped") {
                        kotlinx.coroutines.delay(backoff)
                        backoff = (backoff * 2).coerceAtMost(30_000L)
                    }
                }
            }
        }
    }

    suspend fun pair(url: String, code: String, deviceName: String) {
        val clean = normalizeUrl(url)
        val res = BridgeApi(clean, null).pair(code, deviceName)
        settings.save(clean, res.token)
    }

    suspend fun unpair() = settings.clear()

    fun normalizeUrl(input: String): String {
        var u = input.trim().trimEnd('/')
        if (!u.startsWith("http://") && !u.startsWith("https://")) u = "http://$u"
        if (Regex("^http://[^/:]+$").matches(u)) u += ":8700"   // https (Tailscale) uses the normal port
        return u
    }
}
