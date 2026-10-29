package org.recompile.mobile;

/** Presentation boundary for software M3G passes. No model, texture or game policy. */
public final class M3gPresentation {
    private static final ThreadLocal<Pass> ACTIVE=new ThreadLocal<Pass>();
    private M3gPresentation() {}

    public static Pass begin(Object target,int x,int y,int width,int height) {
        PlatformImage image=target instanceof PlatformGraphics?((PlatformGraphics)target).baseImage:null;
        Pass pass=new Pass(ACTIVE.get(),image,x,y,width,height);
        ACTIVE.set(pass);
        if(pass.parent==null&&image!=null)RuntimeAssets.beginMutation(image);
        return pass;
    }

    public static final class Pass implements AutoCloseable {
        private final Pass parent;
        private final PlatformImage image;
        private final int x,y,width,height;
        private boolean closed;
        private Pass(Pass parent,PlatformImage image,int x,int y,int width,int height) {
            this.parent=parent;this.image=image;this.x=x;this.y=y;this.width=width;this.height=height;
        }
        public void close() {
            if(closed)return;closed=true;
            if(parent==null)ACTIVE.remove();else ACTIVE.set(parent);
            if(parent!=null||image==null)return;
            try {
                // Snapshot only the captured viewport. Unrelated HD pixels and
                // later 2D commands retain their original content and ordering.
                if(width>0&&height>0)Enhancement.sync(image,x,y,width,height);
            } finally {RuntimeAssets.endMutation(image);}
        }
    }
}
