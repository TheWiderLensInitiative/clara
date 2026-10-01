package dev.clara.app.vault

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.SecureRandom
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

@Serializable
data class PhoneLogin(val name: String, val site: String, val username: String, val password: String)

@Serializable
private data class VaultFile(val logins: List<PhoneLogin> = emptyList())

@Serializable
data class Sealed(val approve: Boolean, val phone_pub: String, val nonce: String, val ct: String)  // no defaults: kotlinx omits them

/**
 * Passwords live only here, on the phone, encrypted with a hardware-backed Android Keystore key that can't be exported.
 * When Clara signs in, [seal] encrypts one login to her sign-in tool's one-time key (ECDH P-256 + HKDF-SHA256 +
 * AES-256-GCM, AAD = requestId|name|site), so nothing in between — including the Bridge — can read it.
 */
class PhoneVault(context: Context) {
    private val file = File(context.filesDir, "vault.bin")
    private val json = Json { ignoreUnknownKeys = true }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return gen.generateKey()
    }

    @Synchronized
    fun logins(): List<PhoneLogin> {
        if (!file.exists()) return emptyList()
        val bytes = file.readBytes()
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return json.decodeFromString<VaultFile>(c.doFinal(bytes, 12, bytes.size - 12).decodeToString()).logins
    }

    @Synchronized
    private fun write(logins: List<PhoneLogin>) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val out = c.iv + c.doFinal(json.encodeToString(VaultFile.serializer(), VaultFile(logins)).encodeToByteArray())
        val tmp = File(file.path + ".tmp"); tmp.writeBytes(out); tmp.renameTo(file)
    }

    fun save(login: PhoneLogin) = write(logins().filterNot { it.name == login.name } + login)
    fun delete(name: String) = write(logins().filterNot { it.name == name })

    /** Encrypt one login for Clara's sign-in tool. Returns null if this phone has no login by that name. */
    fun seal(requestId: String, name: String, toolPubB64: String): Sealed? {
        val login = logins().firstOrNull { it.name == name } ?: return null
        val toolPub = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Base64.decode(toolPubB64, Base64.NO_WRAP)))
        val mine = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val shared = KeyAgreement.getInstance("ECDH").run { init(mine.private); doPhase(toolPub, true); generateSecret() }
        val aesKey = hkdfSha256(shared, salt = requestId.encodeToByteArray(), info = "clara-vault-v1".encodeToByteArray(), length = 32)
        shared.fill(0)
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(aesKey, "AES"), GCMParameterSpec(128, nonce))
        c.updateAAD("$requestId|$name|${login.site}".encodeToByteArray())
        val payload = json.encodeToString(mapOf("username" to login.username, "password" to login.password)).encodeToByteArray()
        val ct = c.doFinal(payload)
        payload.fill(0); aesKey.fill(0)
        val b = { x: ByteArray -> Base64.encodeToString(x, Base64.NO_WRAP) }
        return Sealed(approve = true, phone_pub = b(mine.public.encoded), nonce = b(nonce), ct = b(ct))
    }

    companion object {
        private const val ALIAS = "clara_vault_v1"

        /** RFC 5869 HKDF with HMAC-SHA256 (extract then expand). */
        fun hkdfSha256(ikm: ByteArray, salt: ByteArray, info: ByteArray, length: Int): ByteArray {
            val prk = Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(salt, "HmacSHA256")); doFinal(ikm) }
            val out = ByteArray(length); var t = ByteArray(0); var pos = 0; var i = 1
            while (pos < length) {
                t = Mac.getInstance("HmacSHA256").run { init(SecretKeySpec(prk, "HmacSHA256")); update(t); update(info); update(i.toByte()); doFinal() }
                val n = minOf(t.size, length - pos); System.arraycopy(t, 0, out, pos, n); pos += n; i++
            }
            return out
        }
    }
}
