/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/** Count- and byte-bounded handoff from image IO to completed-frame commits. */
final class TextureUpdateQueue {
    private static final int MAX_UPDATES = 64;
    private static final long MAX_BYTES = 64L * 1024L * 1024L;
    private final ArrayDeque<TextureUpdate> queue = new ArrayDeque<TextureUpdate>();
    private long bytes;

    synchronized boolean offer(TextureUpdate update) {
        long size = (long) update.decodedTexture.getWidth() * update.decodedTexture.getHeight() * 4L;
        if (queue.size() >= MAX_UPDATES || size <= 0L || size > MAX_BYTES - bytes) return false;
        queue.addLast(update);
        bytes += size;
        return true;
    }

    synchronized List<TextureUpdate> drain(int maxUpdates, long maxBytes) {
        List<TextureUpdate> result = new ArrayList<TextureUpdate>();
        long drained = 0L;
        while (!queue.isEmpty() && result.size() < maxUpdates) {
            TextureUpdate next = queue.peekFirst();
            long size = (long) next.decodedTexture.getWidth() * next.decodedTexture.getHeight() * 4L;
            if (drained + size > maxBytes) break;
            queue.removeFirst();
            bytes -= size;
            drained += size;
            result.add(next);
        }
        return result;
    }

    synchronized boolean isEmpty() { return queue.isEmpty(); }
    synchronized int size() { return queue.size(); }
}
