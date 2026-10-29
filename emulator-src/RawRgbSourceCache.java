/* JAR Revival additions, GPL-3.0-or-later. */
package org.recompile.mobile;

import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Bounded exact-content snapshots for drawRGB callers that reuse their arrays. */
final class RawRgbSourceCache {
    private static final int MAX_ENTRIES = 256;
    private static final long MAX_BYTES = 4L * 1024L * 1024L;
    private static final LinkedHashMap<Long, Entry> SOURCES =
            new LinkedHashMap<Long, Entry>(64, .75f, true);
    private static final IdentityHashMap<PlatformImage, Entry> IMAGES =
            new IdentityHashMap<PlatformImage, Entry>();
    private static long bytes;

    private RawRgbSourceCache() { }

    static synchronized PlatformImage acquire(int[] pixels, int offset, int scanLength,
                                               int width, int height, boolean processAlpha,
                                               long frame) {
        if (!CaptureAdmission.rawRgbAllowed(offset, scanLength, width, height,
                pixels == null ? 0 : pixels.length)) return null;
        long key = fingerprint(pixels, offset, scanLength, width, height, processAlpha);
        Entry entry = SOURCES.get(key);
        if (entry != null && !matches(entry.image, pixels, offset, scanLength,
                width, height, processAlpha)) {
            // Fingerprints accelerate lookup; complete normalized pixels decide equality.
            SOURCES.remove(key);
            remove(entry);
            entry = null;
        }
        if (entry == null) {
            long required = (long) width * height * 4L;
            Iterator<Map.Entry<Long, Entry>> oldest = SOURCES.entrySet().iterator();
            while ((SOURCES.size() >= MAX_ENTRIES || bytes + required > MAX_BYTES) && oldest.hasNext()) {
                remove(oldest.next().getValue());
                oldest.remove();
            }
            int[] snapshot = new int[width * height];
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
                snapshot[y * width + x] = normalize(pixels[offset + y * scanLength + x], processAlpha);
            entry = new Entry(new PlatformImage(snapshot, width, height, true), required);
            SOURCES.put(key, entry);
            IMAGES.put(entry.image, entry);
            bytes += required;
        }
        if (entry.lastFrame != frame) {
            entry.lastFrame = frame;
            entry.seenFrames = Math.min(CaptureAdmission.STABLE_FRAMES_REQUIRED, entry.seenFrames + 1);
        }
        return entry.image;
    }

    /** Changing blocks receive GPU filtering without immediately creating model jobs. */
    static synchronized boolean captureAllowed(PlatformImage image) {
        Entry entry = IMAGES.get(image);
        return entry == null || entry.seenFrames >= CaptureAdmission.STABLE_FRAMES_REQUIRED;
    }

    private static long fingerprint(int[] pixels, int offset, int scanLength,
                                     int width, int height, boolean processAlpha) {
        long hash = (0xcbf29ce484222325L ^ width) * 0x100000001b3L;
        hash = (hash ^ height) * 0x100000001b3L;
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
            hash = (hash ^ normalize(pixels[offset + y * scanLength + x], processAlpha)) * 0x100000001b3L;
        return hash;
    }

    private static boolean matches(PlatformImage image, int[] pixels, int offset, int scanLength,
                                     int width, int height, boolean processAlpha) {
        if (image.getWidth() != width || image.getHeight() != height) return false;
        int[] existing = image.getDataBuffer();
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++)
            if (existing[y * width + x] != normalize(pixels[offset + y * scanLength + x], processAlpha)) return false;
        return true;
    }

    private static int normalize(int pixel, boolean processAlpha) {
        return !processAlpha ? pixel | 0xff000000 : pixel >>> 24 == 0 ? 0 : pixel;
    }

    private static void remove(Entry entry) {
        IMAGES.remove(entry.image);
        bytes -= entry.bytes;
    }

    static synchronized int retainedSources() { return SOURCES.size(); }
    static synchronized long retainedBytes() { return bytes; }

    private static final class Entry {
        final PlatformImage image;
        final long bytes;
        long lastFrame = Long.MIN_VALUE;
        int seenFrames;
        Entry(PlatformImage image, long bytes) { this.image = image; this.bytes = bytes; }
    }
}
