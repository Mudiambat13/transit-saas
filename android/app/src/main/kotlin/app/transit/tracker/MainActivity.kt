package app.transit.tracker

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.IOException

/** Écran unique : connexion → choix du voyage → suivi. Interface construite en code (aucune dépendance). */
class MainActivity : Activity() {
    private lateinit var prefs: Prefs
    private lateinit var api: Api
    private lateinit var root: LinearLayout
    private val ui = Handler(Looper.getMainLooper())
    private var pendingTrip: Trip? = null
    private var statusView: TextView? = null
    private val refreshStatus = object : Runnable {
        override fun run() { updateStatus(); ui.postDelayed(this, 2000) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        api = Api(prefs)
        val scroll = ScrollView(this)
        scroll.setBackgroundColor(Color.parseColor("#F1F5F9"))
        scroll.isFillViewport = true
        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(20), dp(36), dp(20), dp(28)) }
        scroll.addView(root)
        setContentView(scroll)
    }

    override fun onResume() {
        super.onResume()
        render()
        ui.post(refreshStatus)
    }

    override fun onPause() { ui.removeCallbacks(refreshStatus); super.onPause() }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun title(t: String) = TextView(this).apply { text = t; textSize = 24f; setTextColor(Color.parseColor("#1E3A8A")); setPadding(0, 0, 0, dp(12)) }
    private fun label(t: String, size: Float = 15f) = TextView(this).apply { text = t; textSize = size; setPadding(0, dp(6), 0, dp(6)) }
    private fun rounded(fill: Int, stroke: Int? = null) = GradientDrawable().apply {
        cornerRadius = dp(12).toFloat(); setColor(fill); if (stroke != null) setStroke(dp(1), stroke)
    }

    /** Bouton plein (principal) ou contour (secondaire / danger), hauteur tactile 52 dp. */
    private fun button(t: String, primary: Boolean = false, danger: Boolean = false, onClick: () -> Unit) = Button(this).apply {
        text = t; isAllCaps = false; textSize = 16f; minimumHeight = dp(52)
        val color = if (danger) Color.parseColor("#B91C1C") else Color.parseColor("#1E3A8A")
        if (primary) { background = rounded(color); setTextColor(Color.WHITE) } else { background = rounded(Color.WHITE, color); setTextColor(color) }
        layoutParams = LinearLayout.LayoutParams(-1, -2).also { it.setMargins(0, dp(6), 0, dp(6)) }
        setOnClickListener { onClick() }
    }
    private fun field(hint: String, value: String = "", password: Boolean = false) = EditText(this).apply {
        this.hint = hint; setText(value); setSingleLine()
        inputType = if (password) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_LONG).show()

    /** Exécute un appel réseau hors du thread principal puis rend le résultat sur l'UI. */
    private fun <T> async(work: () -> T, done: (Result<T>) -> Unit) {
        Thread {
            val r = try { Result.success(work()) } catch (e: Exception) { Result.failure(e) }
            runOnUiThread { if (!isFinishing) done(r) }
        }.start()
    }

    private fun message(e: Throwable): String = when (e) {
        is ApiException -> e.message ?: "Erreur"
        is IOException -> "Réseau indisponible. Vérifiez la connexion et l'adresse du serveur."
        else -> "Erreur : ${e.message}"
    }

    private fun render() {
        root.removeAllViews()
        statusView = null
        when {
            prefs.isTracking -> renderTracking()
            prefs.access.isEmpty() -> renderLogin()
            else -> renderTrips()
        }
    }

    // --- Connexion ---------------------------------------------------------------------------------------------
    private fun renderLogin() {
        root.addView(title("Transit Suivi"))
        root.addView(label("Connectez-vous avec le compte chauffeur (ou adjoint) fourni par la compagnie."))
        val server = field("Adresse du serveur (https://…)", prefs.serverUrl)
        val email = field("Email", prefs.email).apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS }
        val pass = field("Mot de passe", password = true)
        val go = button("Se connecter", primary = true) {}
        go.setOnClickListener {
            val url = server.text.toString().trim()
            if (!(url.startsWith("https://") || (url.startsWith("http://") && BuildConfigDebug.isDebug(this)))) {
                toast("L'adresse doit commencer par https://"); return@setOnClickListener
            }
            prefs.serverUrl = url
            go.isEnabled = false
            async({ api.login(email.text.toString(), pass.text.toString()) }) { r ->
                go.isEnabled = true
                r.onSuccess { render() }.onFailure { toast(message(it)) }
            }
        }
        listOf(server, email, pass, go).forEach { root.addView(it) }
    }

    // --- Choix du voyage ---------------------------------------------------------------------------------------
    private fun renderTrips() {
        root.addView(title("Mes voyages"))
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val info = label("Chargement…")
        root.addView(info); root.addView(box)
        root.addView(button("Actualiser") { render() })
        root.addView(button("Se déconnecter") { prefs.logout(); render() })
        root.addView(batteryButton())

        async({ api.myTrips() }) { r ->
            r.onFailure {
                info.text = message(it)
                if (it is ApiException && it.status == 401) { prefs.logout(); render() }
            }
            r.onSuccess { trips ->
                info.text = if (trips.isEmpty()) "Aucun voyage à suivre pour le moment." else "Touchez « Démarrer » sur le voyage en cours."
                trips.forEach { t -> box.addView(tripCard(t)) }
            }
        }
    }

    private fun tripCard(t: Trip): View = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(12), dp(10), dp(12), dp(10))
        background = rounded(Color.WHITE, Color.parseColor("#CBD5E1"))
        layoutParams = LinearLayout.LayoutParams(-1, -2).also { it.setMargins(0, dp(6), 0, dp(6)) }
        addView(label("${t.reference} · ${t.route}", 17f))
        addView(label("Bus ${t.bus} · ${t.status}"))
        if (t.trackingActive) addView(label("Un suivi est déjà actif sur ce voyage (un nouveau remplacera l'ancien)."))
        addView(button("Démarrer le suivi", primary = true) { askPermissionsThenStart(t) })
    }

    // --- Permissions et démarrage ------------------------------------------------------------------------------
    private fun askPermissionsThenStart(t: Trip) {
        pendingTrip = t
        val need = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            need += Manifest.permission.ACCESS_FINE_LOCATION
            need += Manifest.permission.ACCESS_COARSE_LOCATION
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            need += Manifest.permission.POST_NOTIFICATIONS
        }
        if (need.isEmpty()) beginTracking(t) else requestPermissions(need.toTypedArray(), REQ_PERMS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMS) return
        val fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val t = pendingTrip
        if (fine && t != null) beginTracking(t) else toast("La permission de localisation est nécessaire pour suivre le bus.")
    }

    private fun beginTracking(t: Trip) {
        async({ api.startTracking(t.id, "${Build.MANUFACTURER} ${Build.MODEL}") }) { r ->
            r.onSuccess { token ->
                prefs.deviceToken = token
                prefs.activeTripLabel = "${t.reference} · ${t.route}"
                TrackingService.start(this)
                render()
            }.onFailure { toast(message(it)) }
        }
    }

    // --- Suivi en cours ----------------------------------------------------------------------------------------
    private fun renderTracking() {
        root.addView(title("Suivi actif"))
        root.addView(label(prefs.activeTripLabel, 18f))
        val st = label("", 16f).apply { background = rounded(Color.parseColor("#DCFCE7"), Color.parseColor("#86EFAC")); setPadding(dp(14), dp(12), dp(14), dp(12)) }; statusView = st
        root.addView(st)
        root.addView(label("Vous pouvez verrouiller l'écran ou ouvrir d'autres applications : la position continue d'être envoyée. " +
            "Gardez le GPS activé et ne fermez pas l'application depuis la liste des applications récentes."))
        root.addView(batteryButton())
        root.addView(button("Arrêter le suivi", danger = true) {
            TrackingService.requestStop(this)
            toast("Arrêt en cours…")
        })
        updateStatus()
    }

    private fun updateStatus() {
        val v = statusView ?: return
        if (!prefs.isTracking) { render(); return }  // arrêté (par l'utilisateur ou le serveur)
        // Service absent alors qu'un jeton existe (ex. processus tué) : on le relance.
        if (!TrackingState.running) TrackingService.start(this)
        fun ago(ms: Long) = if (ms == 0L) "—" else "il y a ${(System.currentTimeMillis() - ms) / 1000} s"
        val bad = TrackingState.pending > 0 || TrackingState.message.contains("Hors ligne") || TrackingState.message.contains("refus") || TrackingState.message.contains("désactivé")
        v.background = if (bad) rounded(Color.parseColor("#FEF3C7"), Color.parseColor("#FCD34D")) else rounded(Color.parseColor("#DCFCE7"), Color.parseColor("#86EFAC"))
        v.text = "${TrackingState.message}\nDernière position : ${ago(TrackingState.lastFixMs)}\n" +
            "Dernier envoi : ${ago(TrackingState.lastSentMs)}\nEn attente d'envoi : ${TrackingState.pending}"
    }

    // --- Économie d'énergie ------------------------------------------------------------------------------------
    private fun batteryButton(): Button = button("Autoriser l'app à rester active (batterie)") {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            toast("Déjà autorisé. Sur Tecno, Infinix, Xiaomi, Samsung… vérifiez aussi « démarrage automatique » et « pas de restriction » dans les réglages de l'app.")
        } else {
            try { startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))) }
            catch (_: Exception) { startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
        }
    }

    companion object { private const val REQ_PERMS = 7 }
}

/** `http://` n'est accepté qu'en version debug (serveur de test local). */
object BuildConfigDebug {
    fun isDebug(ctx: android.content.Context): Boolean =
        (ctx.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
}
