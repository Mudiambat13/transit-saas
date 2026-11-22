package app.transit.tracker

import app.transit.tracker.core.TrackPoint
import app.transit.tracker.core.TrackerCore
import app.transit.tracker.core.UploadResponse
import app.transit.tracker.core.Uploader
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

class ApiException(val status: Int, message: String) : Exception(message)

data class Trip(val id: Int, val reference: String, val route: String, val bus: String, val status: String, val trackingActive: Boolean)

/** Client HTTP minimal (HttpURLConnection). Les appels sont bloquants : à lancer hors du thread principal. */
class Api(private val prefs: Prefs) {

    private class Raw(val status: Int, val body: String)

    private fun call(method: String, path: String, body: String? = null, headers: Map<String, String> = emptyMap(), timeoutMs: Int = 20_000): Raw {
        val base = prefs.serverUrl
        if (base.isEmpty()) throw ApiException(0, "Adresse du serveur non renseignée.")
        val c = try { URL("$base/api/v1/$path").openConnection() as HttpURLConnection }
        catch (e: java.net.MalformedURLException) { throw ApiException(0, "Adresse du serveur invalide.") }
        try {
            c.requestMethod = method
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.setRequestProperty("Accept", "application/json")
            headers.forEach { (k, v) -> c.setRequestProperty(k, v) }
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            val stream = if (code >= 400) c.errorStream else c.inputStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            return Raw(code, text)
        } finally {
            c.disconnect()
        }
    }

    private fun detail(r: Raw, fallback: String): String = try { JSONObject(r.body).optString("detail", fallback).ifEmpty { fallback } } catch (_: JSONException) { fallback }

    private fun auth(): Map<String, String> = mapOf("Authorization" to "Bearer ${prefs.access}")

    /** Appel authentifié ; renouvelle le jeton d'accès une fois en cas de 401. */
    private fun authed(method: String, path: String, body: String? = null): Raw {
        var r = call(method, path, body, auth())
        if (r.status == 401 && refreshAccess()) r = call(method, path, body, auth())
        return r
    }

    private fun refreshAccess(): Boolean {
        if (prefs.refresh.isEmpty()) return false
        val r = call("POST", "auth/refresh/", JSONObject().put("refresh", prefs.refresh).toString())
        if (r.status != 200) return false
        return try {
            val j = JSONObject(r.body)
            prefs.access = j.getString("access")
            j.optString("refresh").takeIf { it.isNotEmpty() }?.let { prefs.refresh = it }
            true
        } catch (_: JSONException) { false }
    }

    fun login(email: String, password: String): String {
        val r = call("POST", "auth/login/", JSONObject().put("email", email.trim()).put("password", password).toString())
        if (r.status != 200) throw ApiException(r.status, detail(r, "Connexion impossible (code ${r.status})."))
        val j = JSONObject(r.body)
        prefs.access = j.getString("access")
        prefs.refresh = j.getString("refresh")
        prefs.email = email
        return j.optJSONObject("user")?.optString("full_name").orEmpty()
    }

    fun myTrips(): List<Trip> {
        val r = authed("GET", "tracking/my-trips/")
        if (r.status == 401) throw ApiException(401, "Session expirée, reconnectez-vous.")
        if (r.status == 403) throw ApiException(403, "Ce compte n'a pas le droit d'envoyer la position.")
        if (r.status != 200) throw ApiException(r.status, detail(r, "Erreur serveur (${r.status})."))
        val a = JSONArray(r.body)
        return (0 until a.length()).map {
            val o = a.getJSONObject(it)
            Trip(o.getInt("id"), o.getString("reference"), o.getString("route"), o.optString("bus"), o.optString("status"), o.optBoolean("tracking_active"))
        }
    }

    /** Démarre le suivi d'un voyage. Retourne le jeton appareil (affiché une seule fois par le serveur). */
    fun startTracking(tripId: Int, deviceLabel: String): String {
        val r = authed("POST", "trips/$tripId/tracking/start/", JSONObject().put("device_label", deviceLabel).toString())
        if (r.status != 201) throw ApiException(r.status, detail(r, "Impossible de démarrer le suivi (${r.status})."))
        return JSONObject(r.body).getString("token")
    }

    /** Envoi d'un lot de positions avec le jeton appareil (pas de login nécessaire). */
    fun ingest(token: String, points: List<TrackPoint>): UploadResponse {
        val r = call("POST", "tracking/ingest/", TrackerCore.toJsonBatch(points), mapOf("X-Tracking-Token" to token), timeoutMs = 25_000)
        return UploadResponse(r.status, if (r.status in 400..499) detail(r, "") .ifEmpty { null } else null)
    }

    /** Termine la session côté serveur avec le jeton appareil. Idempotent. */
    fun endTracking(token: String): Boolean {
        val r = call("POST", "tracking/end/", "{}", mapOf("X-Tracking-Token" to token))
        return r.status == 200 || r.status == 401  // 401 : déjà invalide, rien à terminer
    }
}

class HttpUploader(private val api: Api, private val tokenProvider: () -> String) : Uploader {
    @Throws(IOException::class)
    override fun send(points: List<TrackPoint>): UploadResponse = try {
        api.ingest(tokenProvider(), points)
    } catch (e: ApiException) {
        throw IOException(e.message)  // adresse invalide / vide : traité comme « hors ligne », rien n'est perdu
    }
}
