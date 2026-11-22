package app.transit.tracker

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import app.transit.tracker.core.FilePointQueue
import app.transit.tracker.core.FlushEngine
import app.transit.tracker.core.FlushResult
import app.transit.tracker.core.TrackPoint
import app.transit.tracker.core.TrackerCore
import java.io.File

/** État lisible par l'écran (le service tourne dans le même processus). */
object TrackingState {
    @Volatile var running = false
    @Volatile var lastFixMs = 0L
    @Volatile var lastSentMs = 0L
    @Volatile var pending = 0
    @Volatile var message = ""
}

/**
 * Service de premier plan : continue d'enregistrer la position écran verrouillé.
 * Les points sont écrits dans une file sur disque puis envoyés par lots ; hors réseau, rien n'est perdu.
 */
class TrackingService : Service() {
    private lateinit var prefs: Prefs
    private lateinit var queue: FilePointQueue
    private lateinit var engine: FlushEngine
    private lateinit var api: Api
    private lateinit var lm: LocationManager
    private lateinit var worker: HandlerThread
    private lateinit var handler: Handler
    private var wakeLock: PowerManager.WakeLock? = null
    private var lastRecordedMs: Long? = null
    private var listening = false
    @Volatile private var stopping = false

    private val listener = object : LocationListener {
        override fun onLocationChanged(loc: Location) = onFix(loc)
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) { TrackingState.message = "GPS désactivé : activez la localisation." }
        @Deprecated("Obsolète depuis l'API 29") override fun onStatusChanged(p: String?, s: Int, e: Bundle?) {}
    }

    private val flushTask = object : Runnable {
        override fun run() {
            if (stopping) return
            doFlush()
            if (!stopping) handler.postDelayed(this, TrackerCore.FLUSH_EVERY_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        api = Api(prefs)
        queue = FilePointQueue(File(filesDir, "points.csv"))
        engine = FlushEngine(queue, HttpUploader(api) { prefs.deviceToken })
        lm = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        worker = HandlerThread("transit-flush").also { it.start() }
        handler = Handler(worker.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopTracking()
            return START_NOT_STICKY
        }
        // Redémarrage par le système (intent == null) : on ne reprend que si un suivi était en cours.
        if (!prefs.isTracking) { stopSelf(); return START_NOT_STICKY }
        goForeground()
        acquireWakeLock()
        startLocation()
        if (!TrackingState.running) {
            TrackingState.running = true
            TrackingState.message = "Suivi actif"
            handler.removeCallbacks(flushTask)
            handler.post(flushTask)
        }
        return START_STICKY
    }

    @SuppressLint("MissingPermission")
    private fun startLocation() {
        if (listening) return
        try {
            var any = false
            for (p in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
                if (lm.allProviders.contains(p)) {
                    lm.requestLocationUpdates(p, TrackerCore.MIN_INTERVAL_MS, 0f, listener, worker.looper)
                    any = true
                }
            }
            listening = any
            if (!any) TrackingState.message = "Aucun fournisseur de position disponible."
        } catch (_: SecurityException) {
            TrackingState.message = "Permission de localisation refusée."
        }
    }

    private fun onFix(loc: Location) {
        val now = System.currentTimeMillis()
        val acc = if (loc.hasAccuracy()) loc.accuracy.toDouble() else null
        if (!TrackerCore.isValid(loc.latitude, loc.longitude)) return
        if (!TrackerCore.shouldRecord(lastRecordedMs, now, acc)) return
        lastRecordedMs = now
        queue.append(TrackPoint(
            lat = loc.latitude, lon = loc.longitude,
            speedKmh = if (loc.hasSpeed()) loc.speed * 3.6 else null,
            heading = if (loc.hasBearing()) loc.bearing.toDouble() else null,
            accuracyM = acc,
            recordedAtMs = if (loc.time > 0) loc.time else now,
        ))
        TrackingState.lastFixMs = now
        TrackingState.pending = queue.size()
    }

    private fun doFlush() {
        when (val r = engine.flush()) {
            is FlushResult.Empty -> TrackingState.pending = 0
            is FlushResult.Sent -> { TrackingState.lastSentMs = System.currentTimeMillis(); TrackingState.pending = r.remaining; TrackingState.message = "Suivi actif" }
            is FlushResult.Offline -> { TrackingState.pending = r.remaining; TrackingState.message = "Hors ligne : ${r.remaining} position(s) en attente" }
            is FlushResult.Ended -> finishBecause("Le suivi a été terminé : ${r.reason}")
            is FlushResult.InvalidToken -> finishBecause("Jeton de suivi refusé. Redémarrez le suivi.")
        }
    }

    /** Arrêt décidé par le serveur (410/401) : inutile de rappeler le serveur. */
    private fun finishBecause(msg: String) {
        stopping = true
        queue.clear()
        prefs.clearTracking()
        TrackingState.message = msg
        shutdown()
    }

    /** Arrêt demandé par l'utilisateur : dernier envoi, puis fin de session côté serveur. */
    private fun stopTracking() {
        if (stopping) return
        stopping = true
        handler.removeCallbacks(flushTask)
        handler.post {
            try {
                engine.flush()
                val token = prefs.deviceToken
                if (token.isNotEmpty() && api.endTracking(token)) {
                    queue.clear()
                    prefs.clearTracking()
                    TrackingState.message = "Suivi arrêté"
                } else {
                    // Réseau absent : on garde le jeton et la file, l'utilisateur pourra réessayer.
                    TrackingState.message = "Arrêt impossible sans réseau : réessayez."
                    stopping = false
                    handler.post(flushTask)
                    startLocationSafe()
                    return@post
                }
            } catch (_: Exception) {
                TrackingState.message = "Arrêt impossible sans réseau : réessayez."
                stopping = false
                handler.post(flushTask)
                return@post
            }
            shutdown()
        }
    }

    private fun startLocationSafe() { if (!listening) startLocation() }

    private fun shutdown() {
        try { lm.removeUpdates(listener) } catch (_: SecurityException) {}
        listening = false
        TrackingState.running = false
        TrackingState.pending = queue.size()
        releaseWakeLock()
        if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
        stopSelf()
    }

    private fun goForeground() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, TrackingService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        @Suppress("DEPRECATION")
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL) else Notification.Builder(this)
        b.setContentTitle(getString(R.string.notif_title))
            .setContentText(prefs.activeTripLabel.ifEmpty { "Position envoyée en continu" })
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Arrêter", stop).build())
        val n = b.build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        else startForeground(NOTIF_ID, n)
    }

    @SuppressLint("WakelockTimeout")
    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "transit:tracking").also { it.acquire(14 * 60 * 60 * 1000L) }
    }

    private fun releaseWakeLock() { wakeLock?.let { if (it.isHeld) it.release() }; wakeLock = null }

    override fun onDestroy() {
        try { lm.removeUpdates(listener) } catch (_: SecurityException) {}
        releaseWakeLock()
        handler.removeCallbacksAndMessages(null)
        worker.quitSafely()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "app.transit.tracker.STOP"
        private const val CHANNEL = "tracking"
        private const val NOTIF_ID = 42

        fun start(ctx: Context) {
            val i = Intent(ctx, TrackingService::class.java)
            if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
        }

        fun requestStop(ctx: Context) {
            ctx.startService(Intent(ctx, TrackingService::class.java).setAction(ACTION_STOP))
        }
    }
}
