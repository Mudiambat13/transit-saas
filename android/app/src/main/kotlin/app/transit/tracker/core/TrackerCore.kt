package app.transit.tracker.core

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** Règles d'échantillonnage et sérialisation. Kotlin pur (aucune dépendance Android) : testable sur JVM. */
object TrackerCore {
    const val MIN_INTERVAL_MS = 15_000L      // un point toutes les 15 s au plus
    const val FLUSH_EVERY_MS = 15_000L       // tentative d'envoi toutes les 15 s
    const val MAX_BATCH = 100                // < limite serveur (200)
    const val MAX_BATCHES_PER_FLUSH = 50     // plafond : un envoi ne monopolise jamais le téléphone
    const val MAX_QUEUE = 5_000              // ~21 h à 1 point / 15 s ; au-delà, on perd les plus anciens
    const val MAX_ACCURACY_M = 500.0         // points trop imprécis ignorés

    fun shouldRecord(lastRecordedAtMs: Long?, nowMs: Long, accuracyM: Double?): Boolean {
        if (accuracyM != null && accuracyM > MAX_ACCURACY_M) return false
        return lastRecordedAtMs == null || nowMs - lastRecordedAtMs >= MIN_INTERVAL_MS
    }

    fun isValid(lat: Double, lon: Double): Boolean =
        lat.isFinite() && lon.isFinite() && lat in -90.0..90.0 && lon in -180.0..180.0 && !(lat == 0.0 && lon == 0.0)

    fun isoUtc(ms: Long): String {
        val f = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        f.timeZone = TimeZone.getTimeZone("UTC")
        return f.format(Date(ms))
    }

    private fun num(d: Double?): String = if (d == null || !d.isFinite()) "null" else d.toString()

    /** Corps JSON de `POST /api/v1/tracking/ingest/`. Que des nombres et des dates ISO : aucun échappement nécessaire. */
    fun toJsonBatch(points: List<TrackPoint>): String =
        points.joinToString(prefix = "{\"points\":[", postfix = "]}", separator = ",") {
            "{\"lat\":${num(it.lat)},\"lon\":${num(it.lon)},\"speed_kmh\":${num(it.speedKmh)}," +
                "\"heading\":${num(it.heading)},\"accuracy_m\":${num(it.accuracyM)},\"recorded_at\":\"${isoUtc(it.recordedAtMs)}\"}"
        }
}
