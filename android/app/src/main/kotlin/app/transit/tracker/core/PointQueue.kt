package app.transit.tracker.core

import java.io.File

/** File persistante des positions en attente d'envoi (survit au redémarrage du service ou du téléphone). */
interface PointQueue {
    fun append(p: TrackPoint)
    /** Les `max` plus anciens points, sans les retirer. */
    fun peek(max: Int): List<TrackPoint>
    /** Retire les `n` plus anciens points (après confirmation du serveur). Les points ajoutés entre-temps sont conservés. */
    fun drop(n: Int)
    fun size(): Int
    fun clear()
}

/** Une ligne par point : `lat,lon,vitesse,cap,précision,epochMs` (champs facultatifs vides). */
class FilePointQueue(private val file: File, private val maxSize: Int = TrackerCore.MAX_QUEUE) : PointQueue {
    private val lock = Any()
    private var count = -1

    private fun encode(p: TrackPoint) =
        listOf(p.lat.toString(), p.lon.toString(), p.speedKmh?.toString() ?: "", p.heading?.toString() ?: "",
            p.accuracyM?.toString() ?: "", p.recordedAtMs.toString()).joinToString(",")

    private fun decode(line: String): TrackPoint? = try {
        val f = line.split(",")
        if (f.size != 6) null else TrackPoint(
            f[0].toDouble(), f[1].toDouble(), f[2].toDoubleOrNull(), f[3].toDoubleOrNull(), f[4].toDoubleOrNull(), f[5].toLong(),
        ).takeIf { TrackerCore.isValid(it.lat, it.lon) }
    } catch (_: NumberFormatException) {
        null
    }

    /** Lit le fichier une fois et écarte les lignes illisibles (ex. dernière ligne coupée par un arrêt brutal). */
    private fun lines(): List<String> {
        if (!file.exists()) { count = 0; return emptyList() }
        val all = file.readLines().filter { it.isNotBlank() }
        val valid = all.filter { decode(it) != null }
        if (valid.size != all.size) rewrite(valid)
        count = valid.size
        return valid
    }

    private fun rewrite(lines: List<String>) {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(if (lines.isEmpty()) "" else lines.joinToString("\n", postfix = "\n"))
        if (!tmp.renameTo(file)) { file.writeText(tmp.readText()); tmp.delete() }
        count = lines.size
    }

    override fun append(p: TrackPoint) = synchronized(lock) {
        if (count < 0) lines()
        file.appendText(encode(p) + "\n")
        count++
        if (count > maxSize + 200) rewrite(lines().takeLast(maxSize))  // marge pour ne pas réécrire à chaque point
    }

    override fun peek(max: Int): List<TrackPoint> = synchronized(lock) {
        lines().asSequence().take(max).mapNotNull { decode(it) }.toList()
    }

    override fun drop(n: Int) = synchronized(lock) {
        if (n > 0) rewrite(lines().drop(n))
    }

    override fun size(): Int = synchronized(lock) { if (count < 0) lines(); count }

    override fun clear() = synchronized(lock) { rewrite(emptyList()) }
}
