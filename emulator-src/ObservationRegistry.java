/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.util.Map;
import java.util.ArrayList;
import java.util.List;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicLong;

/** Tracks image handles weakly; only the bounded capture queue retains an image strongly. */
final class ObservationRegistry {
    private static final int MAX_HANDLES = 8192;
    private final Map<PlatformImage, Entry> entries = new WeakHashMap<PlatformImage, Entry>();
    private final AtomicLong nextHandle = new AtomicLong(1L);

    synchronized ImageObservation register(PlatformImage image,
                                           ImageObservation.SourceKind kind,
                                           ImageObservation.SurfaceRole role) {
        if (image == null || image.getCanvas() == null) return null;
        Entry existing = entries.get(image);
        long handle = existing == null ? nextHandle.getAndIncrement() : existing.handleId;
        long revision = existing == null ? 0L : existing.revision;
        boolean mutable = image.isMutable();
        ImageObservation observation = new ImageObservation(handle, revision,
                image.getWidth(), image.getHeight(), kind, role, mutable);
        if (existing != null) {
            existing.observation = new ImageObservation(handle, revision,
                    image.getWidth(), image.getHeight(), kind, existing.observation.getSurfaceRole(), mutable);
            return observation;
        }
        if (entries.size() >= MAX_HANDLES) return observation;
        entries.put(image, new Entry(handle, observation));
        return observation;
    }

    synchronized ImageObservation registerDerived(PlatformImage image, PlatformImage parent,
                                                   int x, int y, int width, int height, int transform) {
        ImageObservation child = register(image, ImageObservation.SourceKind.DERIVED,
                ImageObservation.SurfaceRole.OFFSCREEN);
        Entry entry = entries.get(image);
        Entry source = entries.get(parent);
        if (entry != null && child != null && source != null) {
            entry.parentHandleId = source.handleId;
            entry.parentRevision = source.revision;
            entry.cropX = x; entry.cropY = y; entry.cropWidth = width; entry.cropHeight = height;
            entry.transform = transform;
        }
        return child;
    }

    synchronized ImageObservation observation(PlatformImage image) {
        Entry entry = entries.get(image);
        return entry == null ? null : entry.observation;
    }

    synchronized void markScreen(PlatformImage image) {
        ImageObservation old = observation(image);
        if (old == null) old = register(image, ImageObservation.SourceKind.MUTABLE_SNAPSHOT,
                ImageObservation.SurfaceRole.SCREEN);
        Entry entry = entries.get(image);
        if (entry == null || old == null) return;
        entry.observation = new ImageObservation(entry.handleId, entry.revision, old.getWidth(),
                old.getHeight(), old.getSourceKind(), ImageObservation.SurfaceRole.SCREEN, image.isMutable());
        entry.stableFrames = 0;
        entry.sourceUsedThisFrame = false;
    }

    synchronized void sourceUsed(PlatformImage image) {
        Entry entry = entries.get(image);
        if (entry != null && entry.observation.isMutable() &&
                entry.observation.getSurfaceRole() == ImageObservation.SurfaceRole.OFFSCREEN &&
                !entry.mutating) entry.sourceUsedThisFrame = true;
    }

    /** Called once at a completed frame boundary; returns at most eligible snapshots. */
    synchronized List<MutableSnapshotCandidate> completeFrame(int maximum) {
        List<MutableSnapshotCandidate> result = new ArrayList<MutableSnapshotCandidate>();
        for (Map.Entry<PlatformImage, Entry> item : entries.entrySet()) {
            PlatformImage image = item.getKey();
            Entry entry = item.getValue();
            if (image == null || !entry.observation.isMutable() ||
                    entry.observation.getSurfaceRole() != ImageObservation.SurfaceRole.OFFSCREEN) continue;
            if (!entry.mutating && entry.mutated && entry.sourceUsedThisFrame) entry.stableFrames++;
            else entry.stableFrames = 0;
            entry.sourceUsedThisFrame = false;
            if (CaptureAdmission.mutableSnapshotAllowed(entry.observation, entry.mutated,
                    entry.mutating, entry.stableFrames, entry.inFlight, entry.captured)) {
                entry.inFlight = true;
                result.add(new MutableSnapshotCandidate(image, entry.observation));
                if (result.size() >= maximum) break;
            }
        }
        return result;
    }

    synchronized boolean isCurrent(PlatformImage image, long handleId, long revision) {
        Entry entry = entries.get(image);
        return entry != null && entry.handleId == handleId && entry.revision == revision &&
                !entry.mutating && entry.observation.getSurfaceRole() == ImageObservation.SurfaceRole.OFFSCREEN;
    }

    synchronized void captureFinished(long handleId, long revision, boolean success) {
        for (Entry entry : entries.values()) {
            if (entry.handleId == handleId && entry.revision == revision) {
                entry.inFlight = false;
                if (success) entry.captured = true;
                return;
            }
        }
    }

    synchronized boolean identified(PlatformImage image, long handleId, long revision, String sourceId) {
        Entry entry = entries.get(image);
        if (entry == null || entry.handleId != handleId || entry.revision != revision ||
                entry.observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK) return false;
        entry.sourceId = sourceId;
        entry.identifying = false;
        return true;
    }

    synchronized boolean beginIdentification(PlatformImage image) {
        Entry entry = entries.get(image);
        if (entry == null || entry.observation.isMutable() ||
                entry.observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK || entry.identifying)
            return false;
        entry.identifying = true;
        return true;
    }

    synchronized String sourceId(PlatformImage image) {
        Entry entry = entries.get(image);
        return entry == null ? null : entry.sourceId;
    }

    synchronized boolean beginResolution(PlatformImage image, String recipeKey) {
        Entry entry = entries.get(image);
        if (entry == null || entry.sourceId == null || entry.observation.isMutable() ||
                entry.observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK ||
                entry.resolvingRecipe.equals(recipeKey)) return false;
        if (entry.resolvedRecipe.equals(recipeKey)) {
            if (image.hdCanvas != null) return false;
            entry.resolvedRecipe = "";
        }
        entry.resolvingRecipe = recipeKey;
        return true;
    }

    synchronized void resolutionFinished(PlatformImage image, String recipeKey) {
        Entry entry = entries.get(image);
        if (entry != null && entry.resolvingRecipe.equals(recipeKey)) {
            entry.resolvingRecipe = "";
            entry.resolvedRecipe = recipeKey;
        }
    }

    synchronized void resolutionRejected(PlatformImage image, String recipeKey) {
        Entry entry = entries.get(image);
        if (entry != null && entry.resolvingRecipe.equals(recipeKey)) entry.resolvingRecipe = "";
    }

    synchronized PlatformImage validate(long handleId, long revision, String sourceId,
                                        String recipeKey, int width, int height) {
        for (Map.Entry<PlatformImage, Entry> item : entries.entrySet()) {
            Entry entry = item.getValue();
            if (entry.handleId != handleId || entry.revision != revision ||
                    !sourceId.equals(entry.sourceId) || entry.observation.isMutable() ||
                    entry.observation.getSurfaceRole() != ImageObservation.SurfaceRole.ARTWORK ||
                    !entry.resolvingRecipe.equals(recipeKey) ||
                    width != entry.observation.getWidth() || height != entry.observation.getHeight()) continue;
            PlatformImage image = item.getKey();
            if (image != null && !image.isMutable()) return image;
        }
        return null;
    }

    synchronized List<DerivedBinding> derivedFrom(long parentHandleId, long parentRevision, String sourceId) {
        List<DerivedBinding> result = new ArrayList<DerivedBinding>();
        for (Map.Entry<PlatformImage, Entry> item : entries.entrySet()) {
            Entry entry = item.getValue();
            PlatformImage child = item.getKey();
            if (child != null && entry.parentHandleId == parentHandleId &&
                    entry.parentRevision == parentRevision && !child.isMutable() &&
                    entry.cropWidth > 0 && entry.cropHeight > 0) {
                entry.sourceId = sourceId;
                result.add(new DerivedBinding(child, entry.observation, entry.sourceId,
                        entry.cropX, entry.cropY, entry.cropWidth, entry.cropHeight, entry.transform));
            }
        }
        return result;
    }

    synchronized boolean beginCapture(PlatformImage image) {
        Entry entry = entries.get(image);
        if (entry == null || entry.captured || entry.inFlight) return false;
        entry.inFlight = true;
        entry.identifying = true;
        return true;
    }

    synchronized void captureFinished(PlatformImage image, boolean success) {
        Entry entry = entries.get(image);
        if (entry == null) return;
        entry.inFlight = false;
        if (success) entry.captured = true;
        else entry.identifying = false;
    }

    synchronized boolean beginMutation(PlatformImage image) {
        Entry entry = entries.get(image);
        if (entry == null) {
            register(image, ImageObservation.SourceKind.MUTABLE_SNAPSHOT,
                    ImageObservation.SurfaceRole.OFFSCREEN);
            entry = entries.get(image);
        }
        if (entry != null) {
            if (entry.mutationDepth++ > 0) return false;
            entry.revision++;
            entry.mutating = true;
            ImageObservation old = entry.observation;
            ImageObservation.SurfaceRole role = old.getSurfaceRole() == ImageObservation.SurfaceRole.SCREEN
                    ? ImageObservation.SurfaceRole.SCREEN : ImageObservation.SurfaceRole.OFFSCREEN;
            entry.observation = new ImageObservation(old.getHandleId(), entry.revision,
                    image.getWidth(), image.getHeight(), old.getSourceKind(),
                    role, true);
            entry.inFlight = false;
            entry.captured = false;
            entry.mutated = true;
            entry.stableFrames = 0;
            entry.sourceUsedThisFrame = false;
            entry.sourceId = null;
            entry.identifying = false;
            entry.resolvingRecipe = "";
            entry.resolvedRecipe = "";
            return true;
        }
        return false;
    }

    synchronized void endMutation(PlatformImage image) {
        Entry entry = entries.get(image);
        if (entry != null && entry.mutationDepth > 0 && --entry.mutationDepth == 0) {
            entry.mutating = false;
            ImageObservation old = entry.observation;
            entry.observation = new ImageObservation(old.getHandleId(), entry.revision,
                    image.getWidth(), image.getHeight(), ImageObservation.SourceKind.MUTABLE_SNAPSHOT,
                    old.getSurfaceRole(), true);
            entry.stableFrames = 0;
            entry.sourceUsedThisFrame = false;
            entry.sourceId = null;
            entry.identifying = false;
            entry.resolvingRecipe = "";
            entry.resolvedRecipe = "";
        }
    }

    private static final class Entry {
        final long handleId;
        ImageObservation observation;
        long revision;
        boolean inFlight;
        boolean captured;
        boolean identifying;
        boolean mutating;
        boolean mutated;
        boolean sourceUsedThisFrame;
        int mutationDepth;
        int stableFrames;
        String sourceId;
        String resolvingRecipe = "";
        String resolvedRecipe = "";
        long parentHandleId;
        long parentRevision;
        int cropX, cropY, cropWidth, cropHeight, transform;
        Entry(long handleId, ImageObservation observation) {
            this.handleId = handleId;
            this.observation = observation;
        }
    }

    static final class MutableSnapshotCandidate {
        final PlatformImage image;
        final ImageObservation observation;
        MutableSnapshotCandidate(PlatformImage image, ImageObservation observation) {
            this.image = image;
            this.observation = observation;
        }
    }

    static final class DerivedBinding {
        final PlatformImage image;
        final ImageObservation observation;
        final String sourceId;
        final int x, y, width, height, transform;
        DerivedBinding(PlatformImage image, ImageObservation observation, String sourceId,
                       int x, int y, int width, int height, int transform) {
            this.image = image; this.observation = observation; this.sourceId = sourceId;
            this.x = x; this.y = y; this.width = width; this.height = height; this.transform = transform;
        }
    }
}
