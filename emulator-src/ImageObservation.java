/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

/** Immutable description of a decoded image at an observation point. */
public final class ImageObservation {
    public enum SourceKind { RESOURCE, ENCODED, RGB, MUTABLE_SNAPSHOT, DERIVED }
    public enum SurfaceRole { ARTWORK, OFFSCREEN, SCREEN }

    private final long handleId;
    private final long revision;
    private final int width;
    private final int height;
    private final SourceKind sourceKind;
    private final SurfaceRole surfaceRole;
    private final boolean mutable;

    ImageObservation(long handleId, long revision, int width, int height,
                     SourceKind sourceKind, SurfaceRole surfaceRole, boolean mutable) {
        this.handleId = handleId;
        this.revision = revision;
        this.width = width;
        this.height = height;
        this.sourceKind = sourceKind;
        this.surfaceRole = surfaceRole;
        this.mutable = mutable;
    }

    public long getHandleId() { return handleId; }
    public long getRevision() { return revision; }
    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public SourceKind getSourceKind() { return sourceKind; }
    public SurfaceRole getSurfaceRole() { return surfaceRole; }
    public boolean isMutable() { return mutable; }
}
