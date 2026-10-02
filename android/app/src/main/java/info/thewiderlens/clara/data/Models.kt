package info.thewiderlens.clara.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class PairResponse(@SerialName("device_id") val deviceId: String, val token: String)

@Serializable
data class Addresses(val lan: String? = null, val remote: String? = null)

@Serializable
data class Health(
    val bridge: String = "",
    val router: Boolean = false,
    val hermes: Boolean = false,
    val model: Boolean = false,
)

@Serializable
data class Conversation(
    val id: String,
    val title: String = "New chat",
    val created: Double = 0.0,
    val updated: Double = 0.0,
    @SerialName("active_run") val activeRun: String? = null,
)

@Serializable
data class ConversationList(val conversations: List<Conversation>)

@Serializable
data class Message(
    val id: String,
    @SerialName("conversation_id") val conversationId: String,
    val role: String,
    val content: String,
    val route: String? = null,
    @SerialName("run_id") val runId: String? = null,
    val created: Double = 0.0,
    val attachments: List<String> = emptyList(),   // workspace paths, e.g. uploads/20260930-photo.jpg
    val suggestions: List<String> = emptyList(),   // tap-to-send replies Clara offers
    val meta: Map<String, String>? = null,         // e.g. kind=checkin, goal_id=…
)

@Serializable
data class VoiceOption(val id: String, val name: String)

@Serializable
data class VoiceSettings(val voice: String = "af_heart", val speed: Double = 1.05, val voices: List<VoiceOption> = emptyList())

@Serializable
data class Upload(val path: String, val name: String, val kind: String, val size: Long = 0)

@Serializable
data class MessageList(val messages: List<Message>)

@Serializable
data class SendResponse(val message: Message, val route: String, val source: String)

@Serializable
data class Approval(
    val id: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("run_id") val runId: String? = null,
    val description: String = "",
    val command: String = "",
    val choices: List<String> = emptyList(),
    val status: String = "pending",
    val created: Double = 0.0,
)

@Serializable
data class ApprovalList(val approvals: List<Approval>)

@Serializable
data class ActivityItem(
    val id: Long,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("run_id") val runId: String? = null,
    val kind: String,
    val tool: String? = null,
    val detail: String? = null,
    val created: Double = 0.0,
)

@Serializable
data class ActivityList(val activity: List<ActivityItem>)

@Serializable
data class Job(
    val id: String,
    val name: String? = null,
    val prompt: String? = null,
    val enabled: Boolean = true,
    val state: String? = null,
    @SerialName("next_run_at") val nextRunAt: String? = null,
    val schedule: JsonObject? = null,
) {
    val scheduleText: String
        get() = schedule?.get("display")?.toString()?.trim('"') ?: ""
}

@Serializable
data class JobList(val jobs: List<Job> = emptyList())

@Serializable
data class Memory(val user: String = "", val memory: String = "")

/** Clara asking the user to take over her browser (CAPTCHA, 2FA code, a stuck sign-in…). */
@Serializable
data class HelpRequest(val id: String, val reason: String, @SerialName("conversation_id") val conversationId: String? = null)

/** One event from the Bridge's live stream (GET /v1/events). */
sealed interface ClaraEvent {
    data class Routed(val conversationId: String, val messageId: String, val route: String, val source: String) : ClaraEvent
    data class Delta(val conversationId: String, val text: String) : ClaraEvent
    data class Completed(val message: Message) : ClaraEvent
    data class RunStarted(val conversationId: String, val runId: String, val route: String) : ClaraEvent
    data class Activity(val conversationId: String, val kind: String, val tool: String?, val detail: String?) : ClaraEvent
    data class ScreenshotAvailable(val conversationId: String) : ClaraEvent
    data class ApprovalRequested(val approval: Approval) : ClaraEvent
    data class ApprovalResolved(val conversationId: String, val choice: String?) : ClaraEvent
    data class Notification(val message: Message) : ClaraEvent
    data class VaultRequest(val request: info.thewiderlens.clara.data.VaultRequest) : ClaraEvent
    data class VaultResolved(val id: String) : ClaraEvent
    data class ApiRequest(val request: info.thewiderlens.clara.data.ApiRequest) : ClaraEvent
    data class ApiResolved(val id: String) : ClaraEvent
    data class CloudRequest(val request: info.thewiderlens.clara.data.CloudRequest) : ClaraEvent
    data class CloudResolved(val id: String) : ClaraEvent
    data class BudgetSuggestion(val suggestion: info.thewiderlens.clara.data.BudgetSuggestion) : ClaraEvent
    data class BudgetResolved(val id: String) : ClaraEvent
    data class HelpRequested(val help: HelpRequest) : ClaraEvent
    data class HelpResolved(val id: String) : ClaraEvent
    data class CharacterChanged(val style: info.thewiderlens.clara.ui.components.CharacterStyle) : ClaraEvent
    data object Resync : ClaraEvent
    data object Connected : ClaraEvent
    data class Disconnected(val reason: String) : ClaraEvent
}

@Serializable
data class Goal(
    val id: String,
    val title: String,
    val area: String = "General",
    val done: Boolean = false,
    val notes: String? = null,
    val created: Double = 0.0,
    val checkin: String? = "off",                          // off | daily | weekly
    @SerialName("checkin_time") val checkinTime: String? = "19:00",
    @SerialName("checkin_day") val checkinDay: Int? = 6,   // 0=Mon … 6=Sun
    @SerialName("last_checkin") val lastCheckin: Double? = null,
)

@Serializable
data class GoalLogEntry(val kind: String, val text: String, val created: Double = 0.0)

@Serializable
data class GoalLog(val log: List<GoalLogEntry>)

@Serializable
data class ProactiveSettings(
    @SerialName("proactive_daily") val daily: Boolean = true,
    @SerialName("proactive_time") val time: String = "08:30",
    @SerialName("quiet_start") val quietStart: String = "22:00",
    @SerialName("quiet_end") val quietEnd: String = "07:30",
)

@Serializable
data class GoalList(val goals: List<Goal>)

@Serializable
data class LibraryFile(val path: String, val name: String, val size: Long = 0, val modified: Double = 0.0, val kind: String = "file")

@Serializable
data class LibraryList(val files: List<LibraryFile>)

@Serializable
data class Identity(val soul: String = "", val user: String = "", val memory: String = "")

@Serializable
data class SavedLogin(val name: String, val site: String? = null, val username: String? = null)

@Serializable
data class LoginList(val logins: List<SavedLogin>)

@Serializable
data class VaultRequest(
    val id: String,
    val name: String,
    val site: String = "",
    val username: String = "",
    @SerialName("conversation_id") val conversationId: String? = null,
    val pubkey: String = "",
)

@Serializable
data class VaultRequestList(val requests: List<VaultRequest>)

@Serializable
data class ApiService(
    val name: String,
    @SerialName("base_url") val baseUrl: String = "",
    @SerialName("auth_type") val authType: String = "",
    @SerialName("auth_name") val authName: String = "",
    val notes: String = "",
    @SerialName("write_policy") val writePolicy: String = "ask",
    @SerialName("last_used") val lastUsed: Double? = null,
)

@Serializable
data class ApiServiceList(val apis: List<ApiService>)

@Serializable
data class ApiRequest(
    val id: String,
    val service: String,
    val host: String = "",
    val method: String = "GET",
    val path: String = "",
    val body: String = "",
    val write: Boolean = false,
    @SerialName("conversation_id") val conversationId: String? = null,
    val choices: List<String> = emptyList(),
)

@Serializable
data class ApiRequestList(val requests: List<ApiRequest>)

@Serializable
data class CloudRequest(
    val id: String,
    val kind: String = "agent",
    val model: String = "",
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("spent_today") val spentToday: Double = 0.0,
    val cap: Double? = null,
    val choices: List<String> = emptyList(),
    val estimate: Double? = null,     // videos: estimated cost of this request
    val summary: String? = null,      // videos: "2 clips · 8s · 720p 16:9 · narrated · Veo 3.1 Lite"
)

@Serializable
data class ConnectorField(val key: String, val label: String)

@Serializable
data class Connector(
    val provider: String, val name: String = "", val services: List<String> = emptyList(),
    val kind: String = "oauth", val category: String = "Other", val steps: List<String> = emptyList(),
    @SerialName("setup_url") val setupUrl: String? = null, @SerialName("needs_secret") val needsSecret: Boolean = false,
    val fields: List<ConnectorField> = emptyList(), val redirect: String = "http://127.0.0.1:53682/cb",
    @SerialName("has_client") val hasClient: Boolean = false, val connected: Boolean = false, val account: String = "",
    @SerialName("connected_at") val connectedAt: Double? = null, val policy: Map<String, String> = emptyMap(),
)

@Serializable
data class ConnectorList(val connectors: List<Connector>)

@Serializable
data class StartUrl(val url: String)

@Serializable
data class CharacterOptions(val shape: List<String> = emptyList(), val hair: List<String> = emptyList(),
                            val eyes: List<String> = emptyList(), val accessories: List<String> = emptyList())

@Serializable
data class CharacterView(
    val style: info.thewiderlens.clara.ui.components.CharacterStyle = info.thewiderlens.clara.ui.components.CharacterStyle(),
    val presets: Map<String, info.thewiderlens.clara.ui.components.CharacterStyle> = emptyMap(),
    @SerialName("can_undo") val canUndo: Boolean = false,
    val options: CharacterOptions = CharacterOptions(),
)

@Serializable
data class SpendDay(val date: String, val total: Double = 0.0, val kinds: Map<String, Double> = emptyMap())

@Serializable
data class SpendKind(val kind: String, val name: String = "", val cost: Double = 0.0, val count: Int = 0)

@Serializable
data class SpendModel(val model: String, val cost: Double = 0.0)

@Serializable
data class SpendTask(val label: String, val chat: String? = null, val kind: String = "", val cost: Double = 0.0, val calls: Int = 0, val last: Double = 0.0)

@Serializable
data class OpenRouterBalance(
    val balance: Double? = null,
    @SerialName("key_limit") val keyLimit: Double? = null,
    @SerialName("key_remaining") val keyRemaining: Double? = null,
)

@Serializable
data class SpendSummary(
    val today: Double = 0.0, val week: Double = 0.0, val month: Double = 0.0,
    @SerialName("projected_month") val projectedMonth: Double = 0.0,
    @SerialName("all_time") val allTime: Double = 0.0,
    val daily: List<SpendDay> = emptyList(),
    @SerialName("by_kind") val byKind: List<SpendKind> = emptyList(),
    @SerialName("by_model") val byModel: List<SpendModel> = emptyList(),
    @SerialName("top_tasks") val topTasks: List<SpendTask> = emptyList(),
    @SerialName("daily_cap") val dailyCap: Double? = null,
    @SerialName("monthly_cap") val monthlyCap: Double? = null,
    val openrouter: OpenRouterBalance? = null,
)

@Serializable
data class BrandKit(
    val name: String = "", val tagline: String = "", val cta: String = "", val website: String = "",
    val primary: String = "#2F6BFF", val accent: String = "#FFD23F", val text: String = "#FFFFFF",
    val font: String = "Poppins", val logo: String = "", val music: String = "",
    val fonts: List<String> = listOf("Poppins", "Anton", "Bebas Neue"),
)

@Serializable
data class VideoModel(
    val id: String, val name: String = "",
    @SerialName("per_second") val perSecond: Double? = null,
    val resolution: String = "", val durations: List<Int> = emptyList(),
    @SerialName("animates_images") val animatesImages: Boolean = false,
)

@Serializable
data class VideoModelList(val models: List<VideoModel>)

@Serializable
data class BudgetSuggestion(val id: String, val amount: Double, val reason: String = "")

@Serializable
data class SpendItem(val ts: Double, val kind: String, val model: String, val cost: Double)

@Serializable
data class CloudState(
    @SerialName("cloud_agent_model") val agentModel: String = "",
    @SerialName("cloud_image_model") val imageModel: String = "",
    @SerialName("cloud_video_model") val videoModel: String = "",
    @SerialName("cloud_daily_cap") val cap: Double? = null,
    @SerialName("cloud_monthly_cap") val monthlyCap: Double? = null,
    @SerialName("spent_month") val spentMonth: Double = 0.0,
    @SerialName("cloud_always") val always: Boolean = false,
    @SerialName("spent_today") val spentToday: Double = 0.0,
    @SerialName("has_key") val hasKey: Boolean = false,
    val recent: List<SpendItem> = emptyList(),
    val requests: List<CloudRequest> = emptyList(),
    val suggestions: List<BudgetSuggestion> = emptyList(),
)
