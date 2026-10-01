package dev.clara.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class ClaraApp : Application() {
    override fun onCreate() {
        super.onCreate()
        ClaraHub.init(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CH_APPROVALS, "Approvals", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Clara needs your OK before doing something sensitive"
                },
                NotificationChannel(CH_REMINDERS, "Reminders & results", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Reminders and scheduled job results"
                },
                NotificationChannel(CH_REPLIES, "Replies", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Clara finished something you asked while the app was closed"
                },
                NotificationChannel(CH_SERVICE, "Connection", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Keeps Clara connected so approvals and reminders arrive"
                    setShowBadge(false)
                },
            )
        )
    }

    companion object {
        const val CH_APPROVALS = "approvals"
        const val CH_REMINDERS = "reminders"
        const val CH_REPLIES = "replies"
        const val CH_SERVICE = "service"
    }
}
