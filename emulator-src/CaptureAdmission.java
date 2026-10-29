/* JAR Revival additions, GPL-3.0-or-later. */
package org.recompile.mobile;

/** Pure size/role policy for runtime observation. State and quotas live elsewhere. */
final class CaptureAdmission {
    static final int STABLE_FRAMES_REQUIRED = 3;
    static final int MAX_MUTABLE_SNAPSHOT_PIXELS = 65_536;
    static final int MAX_RAW_RGB_PIXELS = 65_536;

    private CaptureAdmission() { }

    static boolean mutableSnapshotAllowed(ImageObservation observation, boolean mutated,
                                          boolean mutating, int stableFrames,
                                          boolean inFlight, boolean alreadyCaptured) {
        return observation != null && observation.isMutable() && mutated && !mutating &&
                observation.getSurfaceRole() == ImageObservation.SurfaceRole.OFFSCREEN &&
                stableFrames >= STABLE_FRAMES_REQUIRED && !inFlight && !alreadyCaptured &&
                pixelsWithin(observation.getWidth(), observation.getHeight(), MAX_MUTABLE_SNAPSHOT_PIXELS);
    }

    static boolean rawRgbAllowed(int offset, int scanLength, int width, int height,
                                 int arrayLength) {
        if (width <= 0 || height <= 0 || pixels(width, height) > MAX_RAW_RGB_PIXELS ||
                arrayLength <= 0 || offset < 0 || offset >= arrayLength || scanLength == 0) return false;
        long first = offset;
        long last = first + (long)(height - 1) * scanLength;
        long min = Math.min(first, last);
        long max = Math.max(first, last) + width;
        return min >= 0 && max <= arrayLength;
    }

    static boolean pixelsWithin(int width, int height, long limit) {
        long pixels = pixels(width, height);
        return pixels > 0 && pixels <= limit;
    }

    private static long pixels(int width, int height) {
        return width <= 0 || height <= 0 ? 0 : (long)width * (long)height;
    }
}
