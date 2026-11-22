package app.transit.tracker.core

import java.io.IOException

data class UploadResponse(val status: Int, val detail: String? = null)

fun interface Uploader {
    /** Envoie un lot. Lève [IOException] si le réseau est indisponible. */
    @Throws(IOException::class)
    fun send(points: List<TrackPoint>): UploadResponse
}

sealed class FlushResult {
    object Empty : FlushResult()
    data class Sent(val sent: Int, val remaining: Int) : FlushResult()
    /** Réseau ou serveur indisponible : on réessaiera au prochain cycle, rien n'est perdu. */
    data class Offline(val remaining: Int) : FlushResult()
    /** Session terminée côté serveur (410) : arrêter le suivi. */
    data class Ended(val reason: String) : FlushResult()
    /** Jeton refusé (401) : arrêter le suivi. */
    object InvalidToken : FlushResult()
}

/** Vide la file par lots. Ne retire de la file que les points confirmés par le serveur. */
class FlushEngine(private val queue: PointQueue, private val uploader: Uploader) {
    fun flush(): FlushResult {
        var sentTotal = 0
        var batches = 0
        while (true) {
            val batch = queue.peek(TrackerCore.MAX_BATCH)
            if (batch.isEmpty()) return if (sentTotal > 0) FlushResult.Sent(sentTotal, 0) else FlushResult.Empty
            if (batches++ >= TrackerCore.MAX_BATCHES_PER_FLUSH) return FlushResult.Sent(sentTotal, queue.size())
            val res = try {
                uploader.send(batch)
            } catch (_: IOException) {
                return FlushResult.Offline(queue.size())
            }
            when {
                res.status == 401 -> return FlushResult.InvalidToken
                res.status == 410 -> return FlushResult.Ended(res.detail ?: "Suivi terminé.")
                // Lot refusé en entier (données invalides) : on l'écarte pour ne pas bloquer la file indéfiniment.
                res.status == 400 -> queue.drop(batch.size)
                res.status !in 200..299 -> return FlushResult.Offline(queue.size())  // 5xx, 429… : réessayer plus tard
                else -> { queue.drop(batch.size); sentTotal += batch.size }
            }
        }
    }
}
