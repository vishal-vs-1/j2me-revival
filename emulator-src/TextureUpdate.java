/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.image.BufferedImage;

/** A validated cache result. Ownership transfers from the repository to the runtime queue. */
public final class TextureUpdate {
    public final long handleId;
    public final long expectedRevision;
    public final String sourceId;
    public final String recipeKey;
    public final int logicalWidth;
    public final int logicalHeight;
    public final BufferedImage decodedTexture;

    TextureUpdate(long handleId, long expectedRevision, String sourceId, String recipeKey,
                  int logicalWidth, int logicalHeight, BufferedImage decodedTexture) {
        this.handleId = handleId;
        this.expectedRevision = expectedRevision;
        this.sourceId = sourceId;
        this.recipeKey = recipeKey;
        this.logicalWidth = logicalWidth;
        this.logicalHeight = logicalHeight;
        this.decodedTexture = decodedTexture;
    }
}
