/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.imageio.ImageIO;

/** Background reader for the service's recipe-ready manifest and validated HD files. */
final class TextureRepository {
    private static final int MAX_REQUESTS = 128;
    private static final int MAX_KNOWN_HANDLES = 8192;
    private static final long MAX_TEXTURE_BYTES = 32L * 1024L * 1024L;
    private static final Pattern SOURCES = Pattern.compile("\\\"sources\\\"\\s*:\\s*\\[(.*?)\\]", Pattern.DOTALL);
    private static final Pattern SOURCE_ID = Pattern.compile("\\\"([0-9a-f]{64})\\\"");
    private final Path pack = new File(System.getProperty("jme.pack", ".")).toPath().toAbsolutePath().normalize();
    private final String recipeKey = System.getProperty("jme.recipeKey", "");
    private final int renderScale = Enhancement.SCALE;
    private final ArrayBlockingQueue<Request> requests = new ArrayBlockingQueue<Request>(MAX_REQUESTS);
    private final LinkedHashMap<Long, Request> known = new LinkedHashMap<Long, Request>();
    private final Thread worker;
    private volatile boolean closing;
    private volatile Set<String> readySources = Collections.emptySet();
    private volatile int recipeScale = 4;
    private long manifestModified = Long.MIN_VALUE;
    private long manifestSize = Long.MIN_VALUE;
    private long nextRefresh;

    TextureRepository() {
        if (!recipeKey.matches("[0-9a-f]{64}") || renderScale <= 1) {
            closing = true;
            worker = null;
            return;
        }
        worker = new Thread(new Runnable() { public void run() { runReader(); } }, "ready-texture-reader");
        worker.setDaemon(true);
        worker.start();
    }

    boolean resolveAsync(long handleId, long revision, String sourceId, int width, int height) {
        if (closing || sourceId == null || !sourceId.matches("[0-9a-f]{64}") || width <= 0 || height <= 0) return false;
        Request request = new Request(handleId, revision, sourceId, recipeKey, width, height);
        synchronized (known) {
            if (!known.containsKey(handleId) && known.size() >= MAX_KNOWN_HANDLES) {
                java.util.Iterator<Long> oldest = known.keySet().iterator();
                if (oldest.hasNext()) { oldest.next(); oldest.remove(); }
            }
            known.put(handleId, request);
        }
        return enqueue(request);
    }

    private boolean enqueue(Request request) {
        synchronized (request) {
            if (closing || request.delivered || request.queued || request.processing ||
                    System.nanoTime() < request.retryAfter) return true;
            request.queued = requests.offer(request);
            return request.queued;
        }
    }

    private void runReader() {
        while (!closing) {
            long now = System.nanoTime();
            if (now >= nextRefresh) refreshManifest();
            List<Request> retry = new ArrayList<Request>();
            synchronized (known) {
                for (Request candidate : known.values()) {
                    if (!candidate.delivered && readySources.contains(candidate.sourceId)) retry.add(candidate);
                }
            }
            for (Request candidate : retry) enqueue(candidate);
            Request request;
            try { request = requests.poll(100L, TimeUnit.MILLISECONDS); }
            catch (InterruptedException interrupted) { if (closing) break; else continue; }
            if (request == null) continue;
            synchronized (request) { request.queued = false; request.processing = true; }
            try {
                if (request.recipeKey.equals("") || !readySources.contains(request.sourceId)) continue;
                TextureUpdate update = load(request);
                if (update != null && RuntimeAssets.offerTextureUpdate(update)) {
                    synchronized (request) { request.delivered = true; request.retryAfter = Long.MAX_VALUE; }
                } else if (update != null) {
                    synchronized (request) { request.retryAfter = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(500L); }
                } else {
                    synchronized (request) { request.retryAfter = System.nanoTime() + TimeUnit.SECONDS.toNanos(5L); }
                }
            } catch (Exception error) {
                System.err.println("Ready texture rejected: " + error);
                synchronized (request) { request.retryAfter = System.nanoTime() + TimeUnit.SECONDS.toNanos(5L); }
            } finally {
                synchronized (request) { request.processing = false; }
            }
        }
    }

    private void refreshManifest() {
        nextRefresh = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(500L);
        Path manifest = pack.resolve(".runtime").resolve("ready").resolve(recipeKey + ".json");
        try {
            long modified = Files.getLastModifiedTime(manifest).toMillis();
            long size = Files.size(manifest);
            if (modified == manifestModified && size == manifestSize) return;
            String json = new String(Files.readAllBytes(manifest), java.nio.charset.StandardCharsets.UTF_8);
            String manifestRecipe = value(json, "recipe_key");
            int scale = integer(json, "scale");
            Matcher sourcesMatch = SOURCES.matcher(json);
            if (!recipeKey.equals(manifestRecipe) || scale < 1 || scale > 4 || !sourcesMatch.find()) {
                readySources = Collections.emptySet();
                manifestModified = modified;
                manifestSize = size;
                return;
            }
            Set<String> parsed = new HashSet<String>();
            Matcher ids = SOURCE_ID.matcher(sourcesMatch.group(1));
            while (ids.find()) parsed.add(ids.group(1));
            readySources = Collections.unmodifiableSet(parsed);
            recipeScale = scale;
            manifestModified = modified;
            manifestSize = size;
        } catch (Exception absentOrInvalid) {
            readySources = Collections.emptySet();
        }
    }

    private TextureUpdate load(Request request) throws Exception {
        int sourceScale = recipeScale;
        long expectedWidth = (long) request.width * sourceScale;
        long expectedHeight = (long) request.height * sourceScale;
        if (expectedWidth > Integer.MAX_VALUE || expectedHeight > Integer.MAX_VALUE ||
                expectedWidth * expectedHeight * 4L > MAX_TEXTURE_BYTES) return null;
        Path file = pack.resolve("textures-cache").resolve(request.recipeKey).resolve(request.sourceId + ".png");
        BufferedImage decoded = ImageIO.read(file.toFile());
        if (decoded == null || decoded.getWidth() != (int) expectedWidth || decoded.getHeight() != (int) expectedHeight)
            throw new IllegalArgumentException("cached texture dimensions do not match its source and recipe");
        int targetWidth = request.width * renderScale;
        int targetHeight = request.height * renderScale;
        BufferedImage result = decoded;
        if (targetWidth != decoded.getWidth() || targetHeight != decoded.getHeight()) {
            long bytes = (long) targetWidth * targetHeight * 4L;
            if (bytes > MAX_TEXTURE_BYTES) return null;
            result = new BufferedImage(targetWidth, targetHeight, BufferedImage.TYPE_INT_ARGB);
            Graphics2D graphics = result.createGraphics();
            graphics.setComposite(java.awt.AlphaComposite.Src);
            graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            graphics.drawImage(decoded, 0, 0, targetWidth, targetHeight, null);
            graphics.dispose();
        }
        return new TextureUpdate(request.handleId, request.revision, request.sourceId,
                request.recipeKey, request.width, request.height, result);
    }

    private static String value(String json, String key) {
        Matcher matcher = Pattern.compile("\\\"" + Pattern.quote(key) + "\\\"\\s*:\\s*\\\"([^\\\"]*)\\\"").matcher(json);
        return matcher.find() ? matcher.group(1) : "";
    }

    private static int integer(String json, String key) {
        Matcher matcher = Pattern.compile("\\\"" + Pattern.quote(key) + "\\\"\\s*:\\s*(\\d+)").matcher(json);
        return matcher.find() ? Integer.parseInt(matcher.group(1)) : -1;
    }

    boolean awaitIdle(long timeoutMillis) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        while (System.nanoTime() < deadline) {
            boolean processing = false;
            synchronized (known) { for (Request item : known.values()) if (item.processing) { processing=true; break; } }
            if (requests.isEmpty() && !processing) return true;
            Thread.sleep(10L);
        }
        return requests.isEmpty();
    }

    void close() {
        closing = true;
        if (worker != null) {
            worker.interrupt();
            try { worker.join(1000L); }
            catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
        }
    }

    private static final class Request {
        final long handleId, revision;
        final String sourceId, recipeKey;
        final int width, height;
        volatile boolean delivered;
        volatile boolean queued;
        volatile boolean processing;
        volatile long retryAfter;
        Request(long handleId, long revision, String sourceId, String recipeKey, int width, int height) {
            this.handleId=handleId; this.revision=revision; this.sourceId=sourceId;
            this.recipeKey=recipeKey; this.width=width; this.height=height;
        }
    }
}
