package app.transit.tracker

import android.content.Context

/** Réglages persistants. Le jeton appareil est un secret : stockage privé de l'app (allowBackup=false). */
class Prefs(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("transit", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server", "") ?: ""
        set(v) { sp.edit().putString("server", v.trim().trimEnd('/')).apply() }
    var email: String
        get() = sp.getString("email", "") ?: ""
        set(v) { sp.edit().putString("email", v.trim()).apply() }
    var access: String
        get() = sp.getString("access", "") ?: ""
        set(v) { sp.edit().putString("access", v).apply() }
    var refresh: String
        get() = sp.getString("refresh", "") ?: ""
        set(v) { sp.edit().putString("refresh", v).apply() }

    /** Suivi en cours (survit à un redémarrage du service). */
    var deviceToken: String
        get() = sp.getString("device_token", "") ?: ""
        set(v) { sp.edit().putString("device_token", v).apply() }
    var activeTripLabel: String
        get() = sp.getString("trip_label", "") ?: ""
        set(v) { sp.edit().putString("trip_label", v).apply() }

    fun logout() { sp.edit().remove("access").remove("refresh").apply() }
    fun clearTracking() { sp.edit().remove("device_token").remove("trip_label").apply() }
    val isTracking get() = deviceToken.isNotEmpty()
}
