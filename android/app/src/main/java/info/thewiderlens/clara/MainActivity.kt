package info.thewiderlens.clara

import androidx.compose.ui.Alignment
import androidx.compose.ui.zIndex
import android.Manifest
import info.thewiderlens.clara.ui.screens.UpdatesPage
import info.thewiderlens.clara.ui.screens.UpcomingPage
import info.thewiderlens.clara.ui.screens.SettingsPage
import info.thewiderlens.clara.ui.screens.VoiceScreen
import info.thewiderlens.clara.ui.screens.PasswordsPage
import info.thewiderlens.clara.ui.screens.ApiKeysPage
import info.thewiderlens.clara.ui.screens.CloudPage
import info.thewiderlens.clara.ui.screens.LiveScreenPage
import info.thewiderlens.clara.ui.screens.LibraryScreen
import info.thewiderlens.clara.ui.screens.IdentityPage
import info.thewiderlens.clara.ui.screens.GoalsScreen
import info.thewiderlens.clara.ui.screens.AssistantHub
import info.thewiderlens.clara.ui.components.ClaraIcons
import androidx.compose.runtime.mutableStateOf
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.activity.compose.BackHandler
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.fragment.app.FragmentActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import info.thewiderlens.clara.service.ClaraService
import info.thewiderlens.clara.ui.ClaraViewModel
import info.thewiderlens.clara.ui.UiState
import info.thewiderlens.clara.ui.screens.ChatScreen
import info.thewiderlens.clara.ui.screens.MoodDemo
import info.thewiderlens.clara.ui.screens.PairScreen
import info.thewiderlens.clara.ui.theme.ClaraColors
import info.thewiderlens.clara.ui.theme.ClaraTheme

class MainActivity : FragmentActivity() {
    private val vm: ClaraViewModel by viewModels()
    private val notifPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        handle(intent)
        setContent {
            ClaraTheme {
                val state by vm.ui.collectAsStateWithLifecycle()
                LaunchedEffect(state.paired) {
                    if (state.paired == true) {
                        if (Build.VERSION.SDK_INT >= 33) notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                        ClaraService.start(this@MainActivity)
                    }
                }
                if (intent?.getBooleanExtra("demo_moods", false) == true) { MoodDemo(); return@ClaraTheme }
                androidx.compose.runtime.CompositionLocalProvider(info.thewiderlens.clara.ui.components.LocalCharacterStyle provides state.character.style) {
                    when (state.paired) {
                        null -> Box(Modifier.fillMaxSize().background(ClaraColors.Black))
                        false -> PairScreen(state, vm::pair)
                        true -> Home(state, vm)
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        intent?.getStringExtra(EXTRA_CONVERSATION)?.let { vm.openConversation(it) }
        if (intent?.getBooleanExtra(EXTRA_OPEN_SCREEN, false) == true) openScreen.value = true
    }

    override fun onStart() { super.onStart(); ClaraHub.appVisible = true }
    override fun onStop() { ClaraHub.appVisible = false; super.onStop() }

    private var credentialSuccess: (() -> Unit)? = null
    private val credentialResult = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val callback = credentialSuccess
        credentialSuccess = null
        if (result.resultCode == android.app.Activity.RESULT_OK) callback?.invoke()
    }

    /** Fingerprint / face / device PIN before a saved login may leave the phone. */
    fun confirmIdentity(title: String, subtitle: String, onOk: () -> Unit) {
        if (Build.VERSION.SDK_INT < 30) {
            val keyguard = getSystemService(android.app.KeyguardManager::class.java)
            @Suppress("DEPRECATION")
            val intent = keyguard.createConfirmDeviceCredentialIntent(title, subtitle)
            if (intent != null) { credentialSuccess = onOk; credentialResult.launch(intent) }
            else android.widget.Toast.makeText(this, "Set a device PIN or screen lock first.", android.widget.Toast.LENGTH_LONG).show()
            return
        }
        val auth = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        if (BiometricManager.from(this).canAuthenticate(auth) != BiometricManager.BIOMETRIC_SUCCESS) {
            android.widget.Toast.makeText(this, "Set up a screen lock or supported biometric first.", android.widget.Toast.LENGTH_LONG).show()
            return
        }
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = onOk()
        })
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder().setTitle(title).setSubtitle(subtitle).setAllowedAuthenticators(auth).build(),
        )
    }

    companion object {
        const val EXTRA_CONVERSATION = "conversation_id"
        const val EXTRA_OPEN_SCREEN = "open_screen"
        val openScreen = kotlinx.coroutines.flow.MutableStateFlow(false)   // a "needs your help" notification was tapped
    }
}

@Composable
private fun Home(state: UiState, vm: ClaraViewModel) {
    var tab by rememberSaveable { mutableIntStateOf(0) }            // 0 Chats · 1 Goals · 2 Library
    var page by rememberSaveable { mutableStateOf<String?>(null) }  // assistant menu and its pages
    var loginPrefill by remember { mutableStateOf<Pair<String, String>?>(null) }   // Connectors -> Passwords with that service filled in
    val api by ClaraHub.api.collectAsStateWithLifecycle()
    val context = androidx.compose.ui.platform.LocalContext.current
    val snack = remember { SnackbarHostState() }
    LaunchedEffect(state.error) { state.error?.let { snack.showSnackbar(it); vm.clearError() } }
    LaunchedEffect(Unit) { vm.refreshUpcoming(); vm.refreshConnectors() }
    val wantScreen by MainActivity.openScreen.collectAsStateWithLifecycle()
    LaunchedEffect(wantScreen) { if (wantScreen) { page = "takeover"; MainActivity.openScreen.value = false } }
    BackHandler(enabled = page != null) { page = if (page == "hub" || page == "voice") null else "hub" }
    val back = { page = "hub" }

    if (page != null) {
        Box(Modifier.fillMaxSize().background(ClaraColors.Black).safeDrawingPadding()) {
            SnackbarHost(snack, Modifier.align(Alignment.BottomCenter).zIndex(1f))   // errors show on every page, not just the chat
            when (page) {
                "voice" -> VoiceScreen(state, onSend = { vm.send(it, voice = true) }, speech = vm::speech, onClose = { page = null })
                "hub" -> AssistantHub(state, onOpen = { page = it }, onBack = { page = null })
                "upcoming" -> UpcomingPage(state, vm::refreshUpcoming, vm::jobAction, back)
                "screen" -> LiveScreenPage(state, api, back)
                "takeover" -> LiveScreenPage(state, api, { page = null }, startInControl = true)
                "updates" -> UpdatesPage(state, vm::refreshActivity, vm::answer, back)
                "identity" -> IdentityPage(state, vm::refreshIdentity, vm::saveIdentity, back)
                "connectors" -> info.thewiderlens.clara.ui.screens.ConnectorsPage(state, vm::refreshConnectors, vm::setConnectorClient, vm::setConnectorToken,
                    onConnect = { p -> vm.connect(p) { url ->
                        runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))) }.isSuccess
                    } }, onDisconnect = vm::disconnect, onPolicy = vm::setConnectorPolicy, onBack = back,
                    onSavedLogin = { name, site -> loginPrefill = name to site; page = "passwords" })
                "look" -> info.thewiderlens.clara.ui.screens.LookPage(state, vm::refreshCharacter, vm::setCharacterPreset, vm::setCharacterStyle, vm::undoCharacter, back)
                "spending" -> info.thewiderlens.clara.ui.screens.SpendingPage(state, vm::refreshSpend, vm::setCaps, back)
                "brand" -> info.thewiderlens.clara.ui.screens.BrandPage(state, vm::refreshBrand, vm::saveBrand, vm::setBrandLogo, vm::removeBrandLogo, vm::libraryBytes, back)
                "settings" -> SettingsPage(state, vm::unpair, back, onVoiceRefresh = vm::refreshVoice, onPickVoice = vm::setVoice, speech = vm::speech,
                    onProactiveRefresh = vm::refreshProactive, onProactive = vm::setProactive,
                    onSendNow = { vm.reachOutNow("suggestions"); page = null })
                "passwords" -> PasswordsPage(state, vm::refreshLogins, vm::saveLogin, vm::deleteLogin,
                    { val fromConnectors = loginPrefill != null; loginPrefill = null; vm.refreshConnectors()
                      page = if (fromConnectors) "connectors" else "hub" }, prefill = loginPrefill)
                "apikeys" -> ApiKeysPage(state, vm::refreshApis, vm::saveApi, vm::deleteApi, back)
                "recipes" -> info.thewiderlens.clara.ui.screens.RecipesPage(state, vm::refreshRecipes, vm::deleteRecipe, back)
                "cloud" -> CloudPage(state, vm::refreshCloud, vm::setOpenRouterKey,
                    { a, i, cap, clear, always -> vm.updateCloud(a, i, cap, clear, always) }, vm::answerBudget, back,
                    onVideoRefresh = vm::refreshVideoModels, onVideoModel = vm::setVideoModel, onSpending = { page = "spending" })
            }
        }
        return
    }

    val itemColors = NavigationBarItemDefaults.colors(
        selectedIconColor = ClaraColors.Text, selectedTextColor = ClaraColors.Text, indicatorColor = ClaraColors.Raised,
        unselectedIconColor = ClaraColors.Muted, unselectedTextColor = ClaraColors.Muted,
    )
    Scaffold(
        containerColor = ClaraColors.Black,
        snackbarHost = { SnackbarHost(snack) },
        bottomBar = {
            NavigationBar(containerColor = ClaraColors.Panel) {
                NavigationBarItem(tab == 0, { tab = 0 }, icon = {
                    BadgedBox(badge = { if (state.pending.isNotEmpty()) Badge(containerColor = ClaraColors.Magenta) { Text("${state.pending.size}") } }) {
                        Image(painterResource(R.drawable.clara_mark), null, Modifier.size(26.dp))
                    }
                }, label = { Text("Chats") }, colors = itemColors)
                NavigationBarItem(tab == 1, { tab = 1 }, icon = { Icon(ClaraIcons.Flag, null) }, label = { Text("Goals") }, colors = itemColors)
                NavigationBarItem(tab == 2, { tab = 2 }, icon = { Icon(ClaraIcons.Folder, null) }, label = { Text("Library") }, colors = itemColors)
            }
        },
    ) { pad ->
        // consumeWindowInsets: the keyboard padding inside the chat must not add the tab bar's height again
        Box(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad)) {
            when (tab) {
                0 -> ChatScreen(state, vm::send, vm::stop, vm::answer, vm::newChat, vm::openConversation, vm::hideLive, onAssistant = { page = "hub" }, onWatch = { page = "screen" }, onTakeOver = { page = "takeover" }, api = api,
                    onVault = { r, ok ->
                        if (!ok) vm.answerVault(r, false)
                        else (context as MainActivity).confirmIdentity("Let Clara sign in to ${r.name}?", r.site) { vm.answerVault(r, true) }
                    },
                    onApi = vm::answerApi, onCloud = vm::answerCloud, onBudget = vm::answerBudget,
                    loadImage = vm::libraryBytes, onDelete = vm::deleteConversation,
                    onAttach = vm::attach, onRemoveDraft = vm::removeDraft, onVoice = { page = "voice" })
                1 -> GoalsScreen(state, vm::refreshGoals, vm::addGoal, vm::toggleGoal, vm::deleteGoal,
                    onPlan = { g -> tab = 0; vm.send("Help me make a simple plan for my goal: ${g.title}") },
                    onCheckin = vm::setCheckin, loadLog = vm::goalLog,
                    onCheckinNow = { g -> tab = 0; vm.reachOutNow("checkin", g.id) })
                2 -> LibraryScreen(state, vm::refreshLibrary, vm::libraryBytes, onDelete = vm::deleteLibraryFile, onSave = vm::saveLibraryFile)
            }
        }
    }
}
