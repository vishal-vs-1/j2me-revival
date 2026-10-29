/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.AlphaComposite;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import javax.imageio.ImageIO;

/** Bounded, single-writer persistence for immutable decoded game artwork. */
final class CaptureWriter {
    private static final int MAX_QUEUE = 64;
    private static final long MAX_RETAINED_BYTES = 32L * 1024L * 1024L;
    private static final long MAX_PIXELS = 4_194_304L;

    private final Path pack = new File(System.getProperty("jme.pack", ".")).toPath().toAbsolutePath().normalize();
    private final ArrayBlockingQueue<Request> queue = new ArrayBlockingQueue<Request>(MAX_QUEUE);
    private final AtomicLong retainedBytes = new AtomicLong();
    private final AtomicInteger outstanding = new AtomicInteger();
    private final AtomicLong sequence = new AtomicLong();
    private final AtomicReference<Throwable> lastFailure = new AtomicReference<Throwable>();
    private final String session = UUID.randomUUID().toString().replace("-", "");
    private final Thread worker;
    private volatile boolean closing;

    CaptureWriter() {
        worker = new Thread(new Runnable() {
            public void run() { runWriter(); }
        }, "decoded-image-capture");
        worker.setDaemon(true);
        worker.start();
    }

    boolean tryOffer(PlatformImage image, ImageObservation observation,
                     CaptureCompletion completion) {
        if (closing || image == null || observation == null || observation.isMutable() ||
                observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK) return false;
        Reservation reservation = reserveSnapshot(observation);
        if (reservation == null) return false;
        Request request = new Request(image, null, observation, reservation.bytes, completion);
        if (!queue.offer(request)) {
            release(reservation);
            return false;
        }
        reservation.used = true;
        return true;
    }

    /** Reserve queue capacity and retained bytes before copying mutable pixels. */
    Reservation reserveSnapshot(ImageObservation observation) {
        if (closing || observation == null ||
                !CaptureAdmission.pixelsWithin(observation.getWidth(), observation.getHeight(), MAX_PIXELS)) return null;
        while (true) {
            int current = outstanding.get();
            if (current >= MAX_QUEUE) return null;
            if (outstanding.compareAndSet(current, current + 1)) break;
        }
        long bytes = (long)observation.getWidth() * observation.getHeight() * 4L;
        if (!reserveBytes(bytes)) {
            outstanding.decrementAndGet();
            return null;
        }
        return new Reservation(observation, bytes);
    }

    boolean submitSnapshot(Reservation reservation, BufferedImage snapshot,
                          CaptureCompletion completion) {
        if (reservation == null || reservation.used || snapshot == null || completion == null ||
                snapshot.getWidth() != reservation.observation.getWidth() ||
                snapshot.getHeight() != reservation.observation.getHeight()) {
            release(reservation);
            return false;
        }
        Request request = new Request(null, snapshot, reservation.observation,
                reservation.bytes, completion);
        if (!queue.offer(request)) {
            release(reservation);
            return false;
        }
        reservation.used = true;
        return true;
    }

    void cancel(Reservation reservation) { release(reservation); }

    private boolean reserveBytes(long bytes) {
        while (true) {
            long current = retainedBytes.get();
            if (bytes > MAX_RETAINED_BYTES - current) return false;
            if (retainedBytes.compareAndSet(current, current + bytes)) return true;
        }
    }

    private void runWriter() {
        while (!closing || !queue.isEmpty()) {
            Request request;
            try { request = queue.poll(100L, TimeUnit.MILLISECONDS); }
            catch (InterruptedException interrupted) { if (closing) break; else continue; }
            if (request == null) continue;
            boolean saved = false;
            try {
                BufferedImage snapshot = request.pixels;
                if (snapshot == null) {
                    BufferedImage canvas = request.image.getCanvas();
                    if (canvas == null || canvas.getWidth() != request.observation.getWidth() ||
                            canvas.getHeight() != request.observation.getHeight() || request.image.isMutable()) continue;
                    snapshot = copy(canvas);
                }
                String sourceId = Enhancement.hash(snapshot);
                if (request.image != null) request.completion.identified(request.image, request.observation, sourceId);
                Path source = pack.resolve("original-assets").resolve(sourceId + ".png");
                Files.createDirectories(source.getParent());
                if (!matches(source, sourceId)) writePngAtomic(snapshot, source);
                writeEvent(request.observation, sourceId);
                saved = true;
            } catch (Throwable failure) {
                lastFailure.set(failure);
                System.err.println("Decoded artwork capture: " + failure);
            } finally {
                retainedBytes.addAndGet(-request.bytes);
                outstanding.decrementAndGet();
                request.completion.finished(request.image, saved);
            }
        }
    }

    private static BufferedImage copy(BufferedImage canvas) {
        BufferedImage snapshot = new BufferedImage(canvas.getWidth(), canvas.getHeight(), BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = snapshot.createGraphics();
        graphics.setComposite(AlphaComposite.Src);
        graphics.drawImage(canvas, 0, 0, null);
        graphics.dispose();
        return snapshot;
    }

    private void release(Reservation reservation) {
        if (reservation == null || reservation.used) return;
        reservation.used = true;
        retainedBytes.addAndGet(-reservation.bytes);
        outstanding.decrementAndGet();
    }

    private static boolean matches(Path source, String sourceId) {
        if (!Files.isRegularFile(source)) return false;
        try {
            BufferedImage existing = ImageIO.read(source.toFile());
            return existing != null && sourceId.equals(Enhancement.hash(existing));
        } catch (Exception ignored) { return false; }
    }

    private static void writePngAtomic(BufferedImage image, Path target) throws Exception {
        Path temporary = target.resolveSibling(target.getFileName().toString() + "." + UUID.randomUUID().toString() + ".tmp");
        try {
            if (!ImageIO.write(image, "PNG", temporary.toFile())) throw new IllegalStateException("PNG encoder is unavailable");
            moveAtomic(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    private void writeEvent(ImageObservation observation, String sourceId) throws Exception {
        long id = sequence.incrementAndGet();
        String eventId = session + "-" + id;
        String origin = observation.getSourceKind().name();
        String json = "{\"schema\":1,\"event_id\":\"" + eventId + "\",\"type\":\"capture-ready\"," +
                "\"source_id\":\"" + sourceId + "\",\"width\":" + observation.getWidth() +
                ",\"height\":" + observation.getHeight() + ",\"origin\":\"" + origin +
                "\",\"source_path\":\"original-assets/" + sourceId + ".png\"}";
        Path directory = pack.resolve(".runtime").resolve("events");
        Files.createDirectories(directory);
        Path target = directory.resolve(eventId + ".json");
        Path temporary = directory.resolve(eventId + ".tmp");
        try {
            Files.write(temporary, json.getBytes(StandardCharsets.UTF_8));
            moveAtomic(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    private static void moveAtomic(Path from, Path to) throws Exception {
        try { Files.move(from, to, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
        catch (AtomicMoveNotSupportedException unsupported) {
            Files.move(from, to, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    boolean awaitIdle(long timeoutMillis) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        while (System.nanoTime() < deadline) {
            if (queue.isEmpty() && retainedBytes.get() == 0L) return true;
            Thread.sleep(10L);
        }
        return queue.isEmpty() && retainedBytes.get() == 0L;
    }

    Throwable lastFailure() { return lastFailure.get(); }

    void close() {
        closing = true;
        try { worker.join(2000L); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
    }

    interface CaptureCompletion {
        void identified(PlatformImage image, ImageObservation observation, String sourceId);
        void finished(PlatformImage image, boolean success);
    }

    private static final class Request {
        final PlatformImage image;
        final BufferedImage pixels;
        final ImageObservation observation;
        final long bytes;
        final CaptureCompletion completion;
        Request(PlatformImage image, BufferedImage pixels, ImageObservation observation,
                long bytes, CaptureCompletion completion) {
            this.image = image;
            this.pixels = pixels;
            this.observation = observation;
            this.bytes = bytes;
            this.completion = completion;
        }
    }

    static final class Reservation {
        final ImageObservation observation;
        final long bytes;
        boolean used;
        Reservation(ImageObservation observation, long bytes) {
            this.observation = observation;
            this.bytes = bytes;
        }
    }
}
