/* Decide when a completed frame needs a window swap. No GL or input dependency. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.util.concurrent.atomic.AtomicBoolean;

public final class FramePresentationPolicy {
    private final AtomicBoolean redraw=new AtomicBoolean(true);
    private long lastFrame=-1;
    private int lastWidth=-1,lastHeight=-1;
    public void requestRedraw(){redraw.set(true);}
    public boolean shouldPresent(long frame,int width,int height) {
        return width>0&&height>0&&(redraw.get()||frame!=lastFrame||width!=lastWidth||height!=lastHeight);
    }
    public void presenting(long frame,int width,int height) {
        redraw.set(false);lastFrame=frame;lastWidth=width;lastHeight=height;
    }
}
