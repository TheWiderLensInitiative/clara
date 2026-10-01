package info.thewiderlens.clara.service

import android.Manifest
import android.app.Notification
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import info.thewiderlens.clara.ClaraApp
import info.thewiderlens.clara.ClaraHub
import info.thewiderlens.clara.MainActivity
import info.thewiderlens.clara.R
import info.thewiderlens.clara.data.Approval
import info.thewiderlens.clara.data.ClaraEvent
import info.thewiderlens.clara.data.Message
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Keeps the Bridge connection open and turns events into notifications. */
class ClaraService : LifecycleService() {

    override fun onCreate() {
        super.onCreate()
        ServiceCompat.startForeground(this, ID_SERVICE, serviceNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING)
        ClaraHub.start()
        lifecycleScope.launch {
            ClaraHub.events.collect { ev ->
                when (ev) {
                    is ClaraEvent.ApprovalRequested -> notifyApproval(ev.approval)
                    is ClaraEvent.ApprovalResolved -> cancelApprovals()
                    is ClaraEvent.Notification -> notifyReminder(ev.message)
                    is ClaraEvent.CloudRequest -> post(
                        ID_APPROVAL_BASE + (ev.request.id.hashCode() and 0xffff),
                        NotificationCompat.Builder(this@ClaraService, ClaraApp.CH_APPROVALS)
                            .setSmallIcon(R.drawable.ic_stat_clara)
                            .setContentTitle(when (ev.request.kind) {
                                "image" -> "Clara wants to generate an image in the cloud"
                                "video" -> "Clara wants to make a video" + (ev.request.estimate?.let { " · about $" + "%.2f".format(it) } ?: "")
                                else -> "Clara wants help from a cloud model"
                            })
                            .setContentText(ev.request.summary ?: ev.request.model)
                            .setPriority(NotificationCompat.PRIORITY_HIGH)
                            .setContentIntent(openApp(ev.request.conversationId))
                            .setAutoCancel(true)
                            .build(),
                    )
                    is ClaraEvent.ApiRequest -> post(
                        ID_APPROVAL_BASE + (ev.request.id.hashCode() and 0xffff),
                        NotificationCompat.Builder(this@ClaraService, ClaraApp.CH_APPROVALS)
                            .setSmallIcon(R.drawable.ic_stat_clara)
                            .setContentTitle(if (ev.request.write) "Clara wants to make a change with ${ev.request.service}" else "Clara wants to use ${ev.request.service}")
                            .setContentText("${ev.request.method} ${ev.request.path}")
                            .setPriority(NotificationCompat.PRIORITY_HIGH)
                            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                            .setContentIntent(openApp(ev.request.conversationId))
                            .setAutoCancel(true)
                            .build(),
                    )
                    is ClaraEvent.VaultRequest -> post(
                        ID_APPROVAL_BASE + (ev.request.id.hashCode() and 0xffff),
                        NotificationCompat.Builder(this@ClaraService, ClaraApp.CH_APPROVALS)
                            .setSmallIcon(R.drawable.ic_stat_clara)
                            .setContentTitle("Clara wants to sign in to ${ev.request.name}")
                            .setContentText("Tap to confirm with your fingerprint")
                            .setPriority(NotificationCompat.PRIORITY_HIGH)
                            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                            .setContentIntent(openApp(ev.request.conversationId))
                            .setAutoCancel(true)
                            .build(),
                    )
                    is ClaraEvent.Completed -> if (!ClaraHub.appVisible) notifyReply(ev.message)
                    else -> {}
                }
            }
        }
    }

    private fun openApp(extra: String? = null): PendingIntent {
        val i = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        extra?.let { i.putExtra(MainActivity.EXTRA_CONVERSATION, it) }
        return PendingIntent.getActivity(this, extra.hashCode(), i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun serviceNotification(): Notification =
        NotificationCompat.Builder(this, ClaraApp.CH_SERVICE)
            .setSmallIcon(R.drawable.ic_stat_clara)
            .setContentTitle("Clara is connected")
            .setContentText("Approvals and reminders will reach you here")
            .setOngoing(true)
            .setContentIntent(openApp())
            .build()

    private fun canNotify() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun post(id: Int, n: Notification) {
        if (canNotify()) NotificationManagerCompat.from(this).notify(id, n)
    }

    private fun notifyApproval(a: Approval) {
        val builder = NotificationCompat.Builder(this, ClaraApp.CH_APPROVALS)
            .setSmallIcon(R.drawable.ic_stat_clara)
            .setContentTitle("Clara needs your OK")
            .setContentText(a.description)
            .setStyle(NotificationCompat.BigTextStyle().bigText(a.description))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setContentIntent(openApp(a.conversationId))
            .setAutoCancel(true)
        // Lock-screen notifications only show that approval is needed, never the command itself.
        builder.setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
        for (choice in listOf("deny", "once")) {
            if (choice !in a.choices) continue
            val i = Intent(this, ApprovalReceiver::class.java).putExtra("id", a.id).putExtra("choice", choice)
            val pi = PendingIntent.getBroadcast(this, (a.id + choice).hashCode(), i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            builder.addAction(0, if (choice == "once") "Approve" else "Deny", pi)
        }
        post(ID_APPROVAL_BASE + (a.id.hashCode() and 0xffff), builder.build())
    }

    private fun cancelApprovals() {
        // An approval was answered somewhere (app, notification, or it expired); refresh what is still pending.
        lifecycleScope.launch {
            val pending = runCatching { ClaraHub.api.first()?.approvals("pending") }.getOrNull() ?: return@launch
            val keep = pending.map { ID_APPROVAL_BASE + (it.id.hashCode() and 0xffff) }.toSet()
            val nm = NotificationManagerCompat.from(this@ClaraService)
            nm.activeNotifications.filter { it.id in ID_APPROVAL_BASE..ID_APPROVAL_BASE + 0xffff && it.id !in keep }.forEach { nm.cancel(it.id) }
        }
    }

    private fun notifyReminder(m: Message) = post(
        m.id.hashCode(),
        NotificationCompat.Builder(this, ClaraApp.CH_REMINDERS)
            .setSmallIcon(R.drawable.ic_stat_clara)
            .setContentTitle("Clara")
            .setContentText(m.content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(m.content))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(openApp(m.conversationId))
            .setAutoCancel(true)
            .build(),
    )

    private fun notifyReply(m: Message) = post(
        m.conversationId.hashCode(),
        NotificationCompat.Builder(this, ClaraApp.CH_REPLIES)
            .setSmallIcon(R.drawable.ic_stat_clara)
            .setContentTitle("Clara")
            .setContentText(m.content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(m.content))
            .setContentIntent(openApp(m.conversationId))
            .setAutoCancel(true)
            .build(),
    )

    companion object {
        const val ID_SERVICE = 1
        const val ID_APPROVAL_BASE = 100_000

        fun start(context: Context) {
            ContextCompat.startForegroundService(context, Intent(context, ClaraService::class.java))
        }
    }
}

/** Approve / Deny buttons on an approval notification. */
class ApprovalReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra("id") ?: return
        val choice = intent.getStringExtra("choice") ?: return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                ClaraHub.init(context)
                val api = ClaraHub.api.first { it != null }!!
                runCatching { api.answer(id, choice) }
                NotificationManagerCompat.from(context).cancel(ClaraService.ID_APPROVAL_BASE + (id.hashCode() and 0xffff))
            } finally {
                pending.finish()
            }
        }
    }
}

/** Reconnect after the phone reboots, if it was paired. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                ClaraHub.init(context)
                if (ClaraHub.settings.current() != null) ClaraService.start(context)
            } finally {
                pending.finish()
            }
        }
    }
}
