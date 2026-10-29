/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.image.BufferedImage;
import java.lang.ref.WeakReference;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Bounded software-renderer ownership for decoded HD image variants. */
final class TexturePool {
    private static final long MAX_BYTES = 128L * 1024L * 1024L;
    private final LinkedHashMap<Long, Binding> bindings = new LinkedHashMap<Long, Binding>();
    private long bytes;

    synchronized boolean bind(long handleId, PlatformImage image, BufferedImage texture) {
        long size = (long) texture.getWidth() * texture.getHeight() * 4L;
        if (size <= 0L || size > MAX_BYTES) return false;
        Binding previous = bindings.remove(handleId);
        if (previous != null) {
            bytes -= previous.bytes;
            PlatformImage old = previous.image.get();
            if (old != null && old.hdCanvas == previous.texture) old.hdCanvas = null;
        }
        Iterator<Map.Entry<Long, Binding>> iterator = bindings.entrySet().iterator();
        while (bytes + size > MAX_BYTES && iterator.hasNext()) {
            Binding evicted = iterator.next().getValue();
            iterator.remove();
            bytes -= evicted.bytes;
            PlatformImage old = evicted.image.get();
            if (old != null && old.hdCanvas == evicted.texture) {
                old.hdCanvas = null;
                old.hdResolvedRecipe = null;
            }
        }
        bindings.put(handleId, new Binding(image, texture, size));
        bytes += size;
        image.hdCanvas = texture;
        return true;
    }

    synchronized void remove(long handleId) {
        Binding removed = bindings.remove(handleId);
        if (removed == null) return;
        bytes -= removed.bytes;
        PlatformImage image = removed.image.get();
        if (image != null && image.hdCanvas == removed.texture) image.hdCanvas = null;
    }

    private static final class Binding {
        final WeakReference<PlatformImage> image;
        final BufferedImage texture;
        final long bytes;
        Binding(PlatformImage image, BufferedImage texture, long bytes) {
            this.image = new WeakReference<PlatformImage>(image);
            this.texture = texture;
            this.bytes = bytes;
        }
    }
}
