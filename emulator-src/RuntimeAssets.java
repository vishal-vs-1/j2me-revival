/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.AlphaComposite;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferInt;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import java.util.List;

/** Generic observation facade shared by all JAR games and decoder paths. */
public final class RuntimeAssets {
    private static final ObservationRegistry REGISTRY = new ObservationRegistry();
    private static final CaptureWriter WRITER = new CaptureWriter();
    private static final TextureRepository REPOSITORY = new TextureRepository();
    private static final TextureUpdateQueue UPDATES = new TextureUpdateQueue();
    private static final TexturePool SOFTWARE_POOL = new TexturePool();
    private static final AtomicLong RAW_HANDLE = new AtomicLong(1L << 60);
    private static final LinkedHashMap<Long, RawCandidate> RAW_RGB =
            new LinkedHashMap<Long, RawCandidate>(256, .75f, true);
    private static volatile long completedFrames;
    private static long lastRawCaptureFrame = -1L;
    private static long lastMutableCaptureNanos;
    private static final String ACTIVE_RECIPE = System.getProperty("jme.recipeKey", "");
    private static volatile boolean closed;

    static {
        Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
            public void run() { close(); }
        }, "decoded-image-capture-shutdown"));
    }

    private RuntimeAssets() { }

    public static void created(PlatformImage image, ImageObservation.SourceKind kind) {
        if (image == null || kind == null) return;
        ImageObservation.SurfaceRole role = kind == ImageObservation.SourceKind.DERIVED || image.isMutable()
                ? ImageObservation.SurfaceRole.OFFSCREEN : ImageObservation.SurfaceRole.ARTWORK;
        REGISTRY.register(image, kind, role);
    }

    public static void created(PlatformImage image, ImageObservation.SourceKind kind,
                               ImageObservation.SurfaceRole role) {
        if (image != null && kind != null && role != null) REGISTRY.register(image, kind, role);
    }

    /** Explicit ownership mark used only by emulator-owned LCD buffers. */
    public static void markScreen(PlatformImage image) {
        if (image != null) REGISTRY.markScreen(image);
    }

    public static void derived(PlatformImage image, PlatformImage parent,
                               int x, int y, int width, int height, int transform) {
        if (image == null) return;
        REGISTRY.registerDerived(image, parent, x, y, width, height, transform);
    }

    /** Called by renderer adapters when an image contributes pixels to a game frame. */
    public static void usedAsSource(final PlatformImage image) {
        if (closed || image == null) return;
        if (!RawRgbSourceCache.captureAllowed(image)) return;
        if (image.isMutable()) {
            if (REGISTRY.observation(image) == null)
                created(image, ImageObservation.SourceKind.MUTABLE_SNAPSHOT, ImageObservation.SurfaceRole.OFFSCREEN);
            REGISTRY.sourceUsed(image);
            return;
        }
        if (System.nanoTime() < image.hdCaptureRetryAfter) return;
        if (image.hdLookupPending || image.hdResolvedRecipe != null && image.hdResolvedRecipe.equals(ACTIVE_RECIPE) ||
                image.hdCaptureObserved && (image.hdSourceId == null || ACTIVE_RECIPE.length() != 64)) return;
        ImageObservation observation = REGISTRY.observation(image);
        if (observation == null) {
            created(image, ImageObservation.SourceKind.RGB);
            observation = REGISTRY.observation(image);
        }
        if (observation == null || observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK) return;
        String sourceId = REGISTRY.sourceId(image);
        if (sourceId != null) {
            requestReadyTexture(image, observation, sourceId);
            return;
        }
        if (image.hdCaptureObserved || System.nanoTime() < image.hdCaptureRetryAfter ||
                !REGISTRY.beginCapture(image)) return;
        image.hdCaptureObserved = true;
        boolean offered = WRITER.tryOffer(image, observation, new CaptureWriter.CaptureCompletion() {
            public void identified(PlatformImage source, ImageObservation observed, String id) {
                if (!REGISTRY.identified(source, observed.getHandleId(), observed.getRevision(), id)) return;
                source.hdSourceId = id;
                source.hdLookupPending = false;
                requestReadyTexture(source, observed, id);
            }
            public void finished(PlatformImage source, boolean success) {
                REGISTRY.captureFinished(source, success);
                if (!success && source.hdSourceId == null) source.hdCaptureObserved = false;
                if (!success) source.hdCaptureRetryAfter = System.nanoTime() + 1_000_000_000L;
            }
        });
        if (!offered) {
            image.hdCaptureObserved = false;
            image.hdCaptureRetryAfter = System.nanoTime() + 1_000_000_000L;
            REGISTRY.captureFinished(image, false);
        }
    }

    private static void requestReadyTexture(PlatformImage image, ImageObservation observation, String sourceId) {
        String recipeKey = ACTIVE_RECIPE;
        if (recipeKey.length() != 64 || image.hdResolvedRecipe != null && image.hdResolvedRecipe.equals(recipeKey) ||
                image.hdLookupPending || !REGISTRY.beginResolution(image, recipeKey)) return;
        image.hdLookupPending = true;
        if (!REPOSITORY.resolveAsync(observation.getHandleId(), observation.getRevision(), sourceId,
                observation.getWidth(), observation.getHeight())) {
            image.hdLookupPending = false;
            REGISTRY.resolutionRejected(image, recipeKey);
        }
    }

    public static void beginMutation(PlatformImage image) {
        if (image != null) {
            ImageObservation observation = REGISTRY.observation(image);
            if (observation == null) {
                created(image, ImageObservation.SourceKind.MUTABLE_SNAPSHOT,
                        ImageObservation.SurfaceRole.OFFSCREEN);
                observation = REGISTRY.observation(image);
            }
            if (observation != null && !image.isMutable()) return;
            if (!REGISTRY.beginMutation(image)) return;
            image.hdSourceId = null;
            image.hdResolvedRecipe = null;
            image.hdLookupPending = false;
            image.hdCaptureObserved = false;
        }
    }

    public static void endMutation(PlatformImage image) {
        if (image != null) REGISTRY.endMutation(image);
    }

    public static void rawRgbUsed(PlatformImage image) { usedAsSource(image); }

    /** Observe only small RGB blocks with the same sampled content across three frames. */
    public static synchronized void rawRgbUsed(final int[] pixels, final int offset,
                                               final int scanLength, final int width,
                                               final int height, final boolean processAlpha) {
        if (closed || !CaptureAdmission.rawRgbAllowed(offset, scanLength, width, height,
                pixels == null ? 0 : pixels.length)) return;
        long fingerprint = rawFingerprint(pixels, offset, scanLength, width, height, processAlpha);
        RawCandidate candidate = RAW_RGB.get(fingerprint);
        if (candidate == null) {
            candidate = new RawCandidate();
            RAW_RGB.put(fingerprint, candidate);
            if (RAW_RGB.size() > 256) RAW_RGB.remove(RAW_RGB.keySet().iterator().next());
        }
        if (candidate.lastFrame == completedFrames) return;
        candidate.stableFrames = candidate.lastFrame == completedFrames - 1 ? candidate.stableFrames + 1 : 1;
        candidate.lastFrame = completedFrames;
        if (candidate.captured || candidate.stableFrames < CaptureAdmission.STABLE_FRAMES_REQUIRED ||
                lastRawCaptureFrame == completedFrames) return;
        ImageObservation observation = new ImageObservation(RAW_HANDLE.incrementAndGet(), 0L,
                width, height, ImageObservation.SourceKind.RGB,
                ImageObservation.SurfaceRole.ARTWORK, false);
        final CaptureWriter.Reservation reservation = WRITER.reserveSnapshot(observation);
        if (reservation == null) return;
        BufferedImage snapshot;
        try {
            snapshot = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
            int[] normalized = ((DataBufferInt)snapshot.getRaster().getDataBuffer()).getData();
            for (int y = 0; y < height; y++) {
                int source = offset + y * scanLength;
                int target = y * width;
                for (int x = 0; x < width; x++) {
                    int pixel = pixels[source + x];
                    normalized[target + x] = processAlpha ? pixel : pixel | 0xff000000;
                }
            }
        } catch (RuntimeException invalid) {
            WRITER.cancel(reservation);
            return;
        }
        final RawCandidate state = candidate;
        boolean offered = WRITER.submitSnapshot(reservation, snapshot, new CaptureWriter.CaptureCompletion() {
            public void identified(PlatformImage image, ImageObservation observed, String id) { }
            public void finished(PlatformImage image, boolean success) { synchronized (RuntimeAssets.class) {
                state.captured = success;
            } }
        });
        if (offered) {
            candidate.captured = true;
            lastRawCaptureFrame = completedFrames;
        }
    }

    public static boolean offerTextureUpdate(TextureUpdate update) { return !closed && UPDATES.offer(update); }
    public static int pendingTextureUpdates() { return UPDATES.size(); }
    static long completedFrameCount() { return completedFrames; }

    /** Commit only after the current game frame has been published. */
    public static void endFrame() {
        for (TextureUpdate update : UPDATES.drain(8, 32L * 1024L * 1024L)) {
            if (!update.recipeKey.equals(ACTIVE_RECIPE)) continue;
            PlatformImage image = REGISTRY.validate(update.handleId, update.expectedRevision,
                    update.sourceId, update.recipeKey, update.logicalWidth, update.logicalHeight);
            if (image == null) continue;
            if (!applyTexture(image, update.decodedTexture, update.handleId, update.recipeKey)) {
                if (GpuRenderer.ENABLED && UPDATES.offer(update)) break;
                REGISTRY.resolutionRejected(image, update.recipeKey);
                image.hdLookupPending = false;
                continue;
            }
            REGISTRY.resolutionFinished(image, update.recipeKey);
            image.hdLookupPending = false;
            image.hdResolvedRecipe = update.recipeKey;
            applyDerived(update.handleId, update.expectedRevision, update.sourceId,
                    update.recipeKey, update.decodedTexture);
        }
        completedFrames++;
        lastRawCaptureFrame = -1L;
        captureStableOffscreen();
    }

    private static void captureStableOffscreen() {
        long now = System.nanoTime();
        if (lastMutableCaptureNanos != 0L && now - lastMutableCaptureNanos < 2_000_000_000L) return;
        List<ObservationRegistry.MutableSnapshotCandidate> candidates = REGISTRY.completeFrame(1);
        if (candidates.isEmpty()) return;
        final ObservationRegistry.MutableSnapshotCandidate candidate = candidates.get(0);
        final PlatformImage image = candidate.image;
        final ImageObservation observation = candidate.observation;
        final CaptureWriter.Reservation reservation = WRITER.reserveSnapshot(observation);
        if (reservation == null) {
            REGISTRY.captureFinished(observation.getHandleId(), observation.getRevision(), false);
            return;
        }
        BufferedImage snapshot;
        synchronized (image) {
            if (!REGISTRY.isCurrent(image, observation.getHandleId(), observation.getRevision())) {
                WRITER.cancel(reservation);
                REGISTRY.captureFinished(observation.getHandleId(), observation.getRevision(), false);
                return;
            }
            BufferedImage canvas = image.getCanvas();
            if (canvas == null) {
                WRITER.cancel(reservation);
                REGISTRY.captureFinished(observation.getHandleId(), observation.getRevision(), false);
                return;
            }
            snapshot = new BufferedImage(canvas.getWidth(), canvas.getHeight(), BufferedImage.TYPE_INT_ARGB);
            java.awt.Graphics2D graphics = snapshot.createGraphics();
            graphics.setComposite(AlphaComposite.Src);
            graphics.drawImage(canvas, 0, 0, null);
            graphics.dispose();
        }
        boolean offered = WRITER.submitSnapshot(reservation, snapshot, new CaptureWriter.CaptureCompletion() {
            public void identified(PlatformImage source, ImageObservation observed, String id) { }
            public void finished(PlatformImage source, boolean success) {
                REGISTRY.captureFinished(observation.getHandleId(), observation.getRevision(), success);
            }
        });
        if (offered) lastMutableCaptureNanos = now;
        else REGISTRY.captureFinished(observation.getHandleId(), observation.getRevision(), false);
    }

    private static long rawFingerprint(int[] pixels, int offset, int scanLength,
                                       int width, int height, boolean processAlpha) {
        long hash = 0xcbf29ce484222325L;
        hash = (hash ^ width) * 0x100000001b3L;
        hash = (hash ^ height) * 0x100000001b3L;
        hash = (hash ^ (processAlpha ? 1 : 0)) * 0x100000001b3L;
        long count = (long)width * height;
        int samples = (int)Math.min(32L, count);
        for (int i = 0; i < samples; i++) {
            long flat = samples == 1 ? 0 : (count - 1) * i / (samples - 1);
            int y = (int)(flat / width), x = (int)(flat % width);
            int pixel = pixels[offset + y * scanLength + x];
            if (!processAlpha) pixel |= 0xff000000;
            hash = (hash ^ pixel) * 0x100000001b3L;
        }
        return hash;
    }

    private static final class RawCandidate {
        int stableFrames;
        long lastFrame = Long.MIN_VALUE;
        volatile boolean captured;
    }

    private static boolean applyTexture(PlatformImage image, BufferedImage texture, long handleId, String recipeKey) {
        if (texture.getWidth() != image.getWidth() * Enhancement.SCALE ||
                texture.getHeight() != image.getHeight() * Enhancement.SCALE) return false;
        if (GpuRenderer.ENABLED) {
            if (!GpuRenderer.stageReplacement(image, texture)) return false;
        } else if (!SOFTWARE_POOL.bind(handleId, image, texture)) return false;
        image.hdResolvedRecipe = recipeKey;
        return true;
    }

    private static void applyDerived(long parentHandleId, long parentRevision, String sourceId,
                                     String recipeKey, BufferedImage parentTexture) {
        List<ObservationRegistry.DerivedBinding> children = REGISTRY.derivedFrom(
                parentHandleId, parentRevision, sourceId);
        int scale = Enhancement.SCALE;
        for (ObservationRegistry.DerivedBinding binding : children) {
            if (binding.image.isMutable()) continue;
            long right = (long) binding.x + binding.width, bottom = (long) binding.y + binding.height;
            if (binding.x < 0 || binding.y < 0 || right > parentTexture.getWidth() / scale ||
                    bottom > parentTexture.getHeight() / scale) continue;
            try {
                java.awt.image.BufferedImage region = parentTexture.getSubimage(binding.x * scale,
                        binding.y * scale, binding.width * scale, binding.height * scale);
                java.awt.image.BufferedImage copy = new java.awt.image.BufferedImage(region.getWidth(),
                        region.getHeight(), java.awt.image.BufferedImage.TYPE_INT_ARGB);
                Graphics2D graphics = copy.createGraphics();
                graphics.setComposite(AlphaComposite.Src); graphics.drawImage(region, 0, 0, null); graphics.dispose();
                java.awt.image.BufferedImage transformed = PlatformImage.transformImage(copy, binding.transform);
                if (transformed.getWidth() != binding.image.getWidth() * scale ||
                        transformed.getHeight() != binding.image.getHeight() * scale) continue;
                if (GpuRenderer.ENABLED) {
                    if (!GpuRenderer.stageReplacement(binding.image, transformed)) continue;
                }
                else if (!SOFTWARE_POOL.bind(binding.observation.getHandleId(), binding.image, transformed)) continue;
                binding.image.hdResolvedRecipe = recipeKey;
                applyDerived(binding.observation.getHandleId(), binding.observation.getRevision(),
                        sourceId, recipeKey, transformed);
            } catch (RuntimeException invalidCrop) {
                System.err.println("Derived texture skipped: " + invalidCrop);
            }
        }
    }

    public static boolean awaitIdle(long timeoutMillis) throws InterruptedException {
        long started = System.nanoTime();
        if (!WRITER.awaitIdle(timeoutMillis)) return false;
        long left = timeoutMillis - java.util.concurrent.TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        return left > 0 && REPOSITORY.awaitIdle(left) && UPDATES.isEmpty();
    }

    public static Throwable lastFailure() { return WRITER.lastFailure(); }

    public static synchronized void close() {
        if (closed) return;
        closed = true;
        WRITER.close();
        REPOSITORY.close();
    }

}
