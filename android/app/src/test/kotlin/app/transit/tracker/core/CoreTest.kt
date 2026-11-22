package app.transit.tracker.core

import java.io.File
import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreTest {
    private fun pt(i: Int, acc: Double? = 10.0) =
        TrackPoint(-11.66 + i * 0.001, 27.47, 50.0, null, acc, 1_700_000_000_000L + i * 15_000L)

    private fun queue(): FilePointQueue {
        val dir = File(System.getProperty("java.io.tmpdir"), "transit-test-" + System.nanoTime()).also { it.mkdirs() }
        return FilePointQueue(File(dir, "q.csv"))
    }

    @Test fun samplingRespectsIntervalAndAccuracy() {
        assertTrue(TrackerCore.shouldRecord(null, 1000, 10.0))
        assertFalse(TrackerCore.shouldRecord(1000, 1000 + TrackerCore.MIN_INTERVAL_MS - 1, 10.0))
        assertTrue(TrackerCore.shouldRecord(1000, 1000 + TrackerCore.MIN_INTERVAL_MS, 10.0))
        assertFalse(TrackerCore.shouldRecord(null, 1000, 900.0))
    }

    @Test fun validityRejectsBadCoordinates() {
        assertTrue(TrackerCore.isValid(-11.66, 27.47))
        assertFalse(TrackerCore.isValid(95.0, 27.0))
        assertFalse(TrackerCore.isValid(-11.0, 200.0))
        assertFalse(TrackerCore.isValid(0.0, 0.0))
        assertFalse(TrackerCore.isValid(Double.NaN, 1.0))
    }

    @Test fun jsonBatchIsWellFormedAndUsesUtcIso() {
        val json = TrackerCore.toJsonBatch(listOf(pt(0), TrackPoint(-11.0, 27.0, null, null, null, 0L)))
        assertEquals("2023-11-14T22:13:20.000Z", TrackerCore.isoUtc(1_700_000_000_000L))
        assertTrue(json.startsWith("{\"points\":[{\"lat\":-11.66,\"lon\":27.47,\"speed_kmh\":50.0,\"heading\":null,\"accuracy_m\":10.0,"))
        assertTrue(json.contains("\"recorded_at\":\"2023-11-14T22:13:20.000Z\""))
        assertTrue(json.contains("\"speed_kmh\":null,\"heading\":null,\"accuracy_m\":null,\"recorded_at\":\"1970-01-01T00:00:00.000Z\""))
        assertTrue(json.endsWith("}]}"))
    }

    @Test fun queueKeepsOrderAndSurvivesReopen() {
        val q = queue()
        (0 until 5).forEach { q.append(pt(it)) }
        assertEquals(5, q.size())
        assertEquals(listOf(0, 1, 2), q.peek(3).map { ((it.lat + 11.66) / 0.001 + 0.5).toInt() })
        q.drop(2)
        assertEquals(3, q.size())
        assertEquals(pt(2), q.peek(1).first())
    }

    @Test fun queueDiscardsCorruptedLines() {
        val dir = File(System.getProperty("java.io.tmpdir"), "transit-corrupt-" + System.nanoTime()).also { it.mkdirs() }
        val f = File(dir, "q.csv")
        f.writeText("-11.66,27.47,50.0,,10.0,1700000000000\nGARBAGE\n-11.67,27.47,,,,17000000150")
        val q = FilePointQueue(f)
        assertEquals(2, q.size())  // la ligne illisible est écartée, la dernière (coupée mais numérique) reste valide
        assertEquals(2, q.peek(10).size)
    }

    @Test fun queueIsCappedKeepingNewestPoints() {
        val dir = File(System.getProperty("java.io.tmpdir"), "transit-cap-" + System.nanoTime()).also { it.mkdirs() }
        val q = FilePointQueue(File(dir, "q.csv"), maxSize = 10)
        (0 until 300).forEach { q.append(pt(it)) }
        assertTrue(q.size() <= 10 + 200)
        assertEquals(pt(299), q.peek(1000).last())
    }

    @Test fun flushKeepsPointsWhileOffline() {
        val q = queue(); (0 until 3).forEach { q.append(pt(it)) }
        val r = FlushEngine(q) { throw IOException("offline") }.flush()
        assertEquals(FlushResult.Offline(3), r)
        assertEquals(3, q.size())
    }

    @Test fun flushClearsQueueAfterConfirmation() {
        val q = queue(); (0 until 2).forEach { q.append(pt(it)) }
        var received = 0
        val r = FlushEngine(q) { received += it.size; UploadResponse(200) }.flush()
        assertEquals(FlushResult.Sent(2, 0), r)
        assertEquals(2, received)
        assertEquals(0, q.size())
    }

    @Test fun flushSplitsLargeBacklogIntoBatchesOf100() {
        val q = queue(); (0 until 250).forEach { q.append(pt(it)) }
        val sizes = mutableListOf<Int>()
        val r = FlushEngine(q) { sizes += it.size; UploadResponse(200) }.flush()
        assertEquals(listOf(100, 100, 50), sizes)
        assertEquals(FlushResult.Sent(250, 0), r)
    }

    @Test fun flushKeepsRemainderWhenNetworkDropsMidway() {
        val q = queue(); (0 until 150).forEach { q.append(pt(it)) }
        var calls = 0
        val r = FlushEngine(q) { if (++calls == 1) UploadResponse(200) else throw IOException("offline") }.flush()
        assertEquals(FlushResult.Offline(50), r)
        assertEquals(50, q.size())
    }

    @Test fun flushKeepsPointsAddedDuringSending() {
        val q = queue(); q.append(pt(0)); q.append(pt(1))
        var first = true
        val r = FlushEngine(q) { if (first) { first = false; q.append(pt(2)) }; UploadResponse(200) }.flush()
        assertEquals(FlushResult.Sent(3, 0), r)
        assertEquals(0, q.size())
    }

    @Test fun flushStopsOnEndedAndInvalidTokenWithoutLosingPoints() {
        val q = queue(); q.append(pt(0))
        assertEquals(FlushResult.Ended("Le voyage est terminé."), FlushEngine(q) { UploadResponse(410, "Le voyage est terminé.") }.flush())
        assertEquals(FlushResult.InvalidToken, FlushEngine(q) { UploadResponse(401) }.flush())
        assertEquals(1, q.size())
    }

    @Test fun flushRetriesLaterOnServerErrorsAndRateLimit() {
        val q = queue(); q.append(pt(0))
        for (code in listOf(500, 502, 429)) assertEquals(FlushResult.Offline(1), FlushEngine(q) { UploadResponse(code) }.flush())
        assertEquals(1, q.size())
    }

    @Test fun flushDropsRejectedBatchSoTheQueueNeverBlocks() {
        val q = queue(); q.append(pt(0)); q.append(pt(1))
        assertEquals(FlushResult.Empty, FlushEngine(q) { UploadResponse(400) }.flush())
        assertEquals(0, q.size())
    }

    @Test fun flushIsBoundedPerCycle() {
        val q = queue(); (0 until 120).forEach { q.append(pt(it)) }
        var calls = 0
        FlushEngine(q) { calls++; UploadResponse(200) }.flush()
        assertTrue(calls <= TrackerCore.MAX_BATCHES_PER_FLUSH)
    }
}
