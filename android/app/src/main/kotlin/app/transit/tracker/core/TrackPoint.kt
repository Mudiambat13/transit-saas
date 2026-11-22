package app.transit.tracker.core

/** Une position GPS à envoyer. `recordedAtMs` : heure d'origine sur le téléphone (epoch, ms). */
data class TrackPoint(
    val lat: Double,
    val lon: Double,
    val speedKmh: Double?,
    val heading: Double?,
    val accuracyM: Double?,
    val recordedAtMs: Long,
)
