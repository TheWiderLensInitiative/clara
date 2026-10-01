package info.thewiderlens.clara.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.store by preferencesDataStore(name = "clara")

data class Pairing(val bridgeUrl: String, val token: String, val lanUrl: String? = null, val remoteUrl: String? = null) {
    /** Where to look for the Bridge, best first: home Wi-Fi addresses, then the Tailscale address (works from anywhere). */
    val addresses: List<String> get() = listOfNotNull(bridgeUrl.takeUnless { it.startsWith("https://") }, lanUrl, remoteUrl,
        bridgeUrl.takeIf { it.startsWith("https://") }).distinct()
}

/** Where the Bridge lives and this phone's device token. App-private storage, never backed up. */
class Settings(private val context: Context) {
    private val urlKey = stringPreferencesKey("bridge_url")
    private val tokenKey = stringPreferencesKey("token")
    private val lanKey = stringPreferencesKey("lan_url")
    private val remoteKey = stringPreferencesKey("remote_url")

    val pairing: Flow<Pairing?> = context.store.data.map { p ->
        val url = p[urlKey]
        val token = p[tokenKey]
        if (url.isNullOrBlank() || token.isNullOrBlank()) null else Pairing(url, token, p[lanKey], p[remoteKey])
    }

    /** Remember the addresses the Bridge reported, so the app can switch between home Wi-Fi and Tailscale by itself. */
    suspend fun saveAddresses(lan: String?, remote: String?) {
        context.store.edit { p ->
            if (lan.isNullOrBlank()) p.remove(lanKey) else p[lanKey] = lan
            if (remote.isNullOrBlank()) p.remove(remoteKey) else p[remoteKey] = remote
        }
    }

    suspend fun current(): Pairing? = pairing.first()

    suspend fun save(url: String, token: String) {
        context.store.edit { it[urlKey] = url; it[tokenKey] = token }
    }

    suspend fun clear() {
        context.store.edit { it.remove(tokenKey) }
    }
}
