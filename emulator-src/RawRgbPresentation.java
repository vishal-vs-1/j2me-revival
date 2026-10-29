/* JAR Revival additions, GPL-3.0-or-later. */
package org.recompile.mobile;

import java.awt.Rectangle;
import java.util.concurrent.atomic.AtomicLong;

/** Adapts direct RGB blocks to the existing native-filter and HD-image blit path. */
final class RawRgbPresentation {
    private static final AtomicLong SUBMITTED_DRAWS = new AtomicLong();

    private RawRgbPresentation() { }

    static Draw prepare(PlatformGraphics graphics, int[] pixels, int offset, int scanLength,
                         int x, int y, int width, int height, boolean processAlpha) {
        if (!GpuRenderer.ENABLED || Enhancement.SCALE <= 1) return null;
        int clipRight = Math.min(graphics.baseImage.getWidth(),
                graphics.getClipWidth() + graphics.getClipX() + graphics.translateX);
        int clipBottom = Math.min(graphics.baseImage.getHeight(),
                graphics.getClipHeight() + graphics.getClipY() + graphics.translateY);
        if (Mobile.compatDoNotTranslateDrawRGB && y + graphics.translateY > clipBottom &&
                (long) x + graphics.translateX + width > clipRight) {
            x -= graphics.translateX;
            y -= graphics.translateY;
        }
        Rectangle clip = graphics.gc.getClipBounds();
        if (clip == null) clip = new Rectangle(-graphics.translateX, -graphics.translateY,
                graphics.baseImage.getWidth(), graphics.baseImage.getHeight());
        if (width <= 0 || height <= 0 || !clip.intersects(x, y, width, height)) return null;
        PlatformImage source = RawRgbSourceCache.acquire(pixels, offset, scanLength,
                width, height, processAlpha, RuntimeAssets.completedFrameCount());
        return source == null ? null : new Draw(source, x, y);
    }

    static long submittedDraws() { return SUBMITTED_DRAWS.get(); }

    static final class Draw {
        private final PlatformImage source;
        private final int x, y;
        private Draw(PlatformImage source, int x, int y) { this.source = source; this.x = x; this.y = y; }
        void render(PlatformGraphics graphics) {
            GpuRenderer.blit(graphics, source, 0, 0, source.getWidth(), source.getHeight(),
                    x, y, source.getWidth(), source.getHeight(), 0, false);
            SUBMITTED_DRAWS.incrementAndGet();
        }
    }
}
