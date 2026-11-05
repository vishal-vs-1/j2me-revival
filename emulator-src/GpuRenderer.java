/* OpenGL compositor for JAR Revival. GPL-3.0-or-later. */
package org.recompile.mobile;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.lang.ref.WeakReference;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.concurrent.LinkedBlockingQueue;
import org.lwjgl.system.MemoryUtil;
import static org.lwjgl.opengl.GL11.*;
import static org.lwjgl.opengl.GL14.glBlendFuncSeparate;
import static org.lwjgl.opengl.GL30.*;

/** GL calls execute only on the native window thread. Game threads record ordered operations. */
public final class GpuRenderer {
    public static final boolean ENABLED=Boolean.getBoolean("jme.gpu");
    private static final LinkedBlockingQueue<Runnable> QUEUE=new LinkedBlockingQueue<Runnable>(8192);
    private static final FrameBackpressure FRAMES=new FrameBackpressure(2);
    private static final WeakHashMap<PlatformImage,Layer> LAYERS=new WeakHashMap<PlatformImage,Layer>();
    private static final ArrayList<Layer> ALLOCATED=new ArrayList<Layer>();
    private static final int S=Enhancement.SCALE;
    private static final class Frame {
        final int w,h,texture,framebuffer;
        Frame(int w,int h) {
            this.w=w;this.h=h;texture=glGenTextures();glBindTexture(GL_TEXTURE_2D,texture);parameters();
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w*S,h*S,0,GL_RGBA,GL_UNSIGNED_BYTE,(ByteBuffer)null);
            framebuffer=glGenFramebuffers();glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
            glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
            if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw new IllegalStateException("Presentation framebuffer incomplete");
            boundFramebuffer=-1;
        }
        void destroy(){glDeleteTextures(texture);glDeleteFramebuffers(framebuffer);}
    }
    private static Frame presented,spare;
    public static volatile long submittedFrames=0;
    public static volatile boolean closing=false;
    public static String device="OpenGL";
    private static int boundFramebuffer=-1;
    private static final int[][] CORNERS={{0,1,2,3},{3,2,1,0},{1,0,3,2},{2,3,0,1},{0,3,2,1},{3,0,1,2},{1,2,3,0},{2,1,0,3}};

    private static final class Layer {
        final int w,h;
        final WeakReference<PlatformImage> owner;
        final BitSet dirty;
        final int[] pending;
        final boolean smoothFallback;
        int texture,framebuffer;
        volatile BufferedImage version;
        Layer(PlatformImage image) {
            w=image.getWidth();h=image.getHeight();owner=new WeakReference<PlatformImage>(image);
            smoothFallback=image.hdGenerated;
            dirty=new BitSet(w*h);pending=new int[w*h];
        }
    }
    private static void enqueue(Runnable command) {
        if(closing)return;
        try { QUEUE.put(command); } catch(InterruptedException error) {Thread.currentThread().interrupt();}
    }
    private static Layer layer(PlatformImage image) {
        Layer result=LAYERS.get(image);
        if(result==null) {
            result=new Layer(image);LAYERS.put(image,result);
            final Layer fresh=result;
            final BufferedImage snapshot=copy(image.getCanvas());
            enqueue(() -> create(fresh,snapshot));
        }
        BufferedImage cached=image.hdCanvas;
        if(!image.isMutable() && cached!=null && result.version!=cached) {
            result.version=cached;
            final Layer target=result;
            enqueue(() -> replace(target,cached));
        }
        return result;
    }
    public static synchronized void observe(PlatformImage image) {layer(image);}
    /** Queue an HD replacement after the current committed frame; GL remains on its owner thread. */
    public static synchronized boolean stageReplacement(final PlatformImage image, final BufferedImage texture) {
        if (closing || image == null || texture == null) return false;
        Layer target=LAYERS.get(image);
        if(target==null) { image.hdCanvas=texture; return true; }
        target.version=texture;
        image.hdCanvas=texture;
        boolean queued=QUEUE.offer(() -> {
            if(target.owner.get()!=image || target.version!=texture)return;
            replace(target,texture);
            if(image.hdCanvas==texture)image.hdCanvas=null;
            target.version=null;
        });
        if(!queued) { target.version=null; if(image.hdCanvas==texture)image.hdCanvas=null; }
        return queued;
    }
    public static synchronized void derive(PlatformImage image,PlatformImage source,int x,int y,int w,int h,int transform) {
        Layer src=layer(source),dst=layer(image);flushDirty(src);
        enqueue(()->draw(src,dst,x,y,w,h,0,0,dst.w,dst.h,transform,true,new Rectangle(0,0,dst.w,dst.h)));
    }
    private static BufferedImage copy(BufferedImage image) {
        BufferedImage result=new BufferedImage(image.getWidth(),image.getHeight(),BufferedImage.TYPE_INT_ARGB);
        result.setRGB(0,0,image.getWidth(),image.getHeight(),image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth()),0,image.getWidth());
        return result;
    }
    public static synchronized void pixel(PlatformImage image,int index,int value) {
        Layer target=layer(image);
        if(index<0 || index>=target.pending.length)return;
        target.pending[index]=value;target.dirty.set(index);
    }
    private static void flushDirty(Layer target) {
        if(target.dirty.isEmpty())return;
        // Snapshot exact dirty regions; keep untouched HD pixels intact.
        PixelUploadBatch batch=PixelUploadBatch.capture(target.dirty,target.pending,target.w);
        enqueue(() -> {
            target(target);glDisable(GL_BLEND);glEnable(GL_TEXTURE_2D);glColor4f(1,1,1,1);
            int temp=glGenTextures();glBindTexture(GL_TEXTURE_2D,temp);parameters();
            for(int[] strip:batch.regions) {
                int[] pixels=new int[strip[2]*strip[3]];
                for(int row=0;row<strip[3];row++)System.arraycopy(batch.pixels,(strip[1]-batch.top+row)*batch.width+strip[0],pixels,row*strip[2],strip[2]);
                upload(pixels,0,strip[2],strip[3]);
                quad(strip[0]*S,strip[1]*S,strip[2]*S,strip[3]*S,0,0,1,1);
            }
            glDeleteTextures(temp);
        });
    }
    public static synchronized void textPatch(PlatformGraphics graphics,int x,int y,int w,int h,int[] pixels,int rasterScale) {
        Layer destination=layer(graphics.baseImage);flushDirty(destination);
        Rectangle clip=clip(graphics);
        enqueue(() -> {
            target(destination);scissor(destination,clip);blend(true);glEnable(GL_TEXTURE_2D);glColor4f(1,1,1,1);
            int temp=glGenTextures();glBindTexture(GL_TEXTURE_2D,temp);parameters();upload(pixels,0,w*rasterScale,h*rasterScale);
            quad(x*S,y*S,w*S,h*S,0,0,1,1);glDeleteTextures(temp);glDisable(GL_SCISSOR_TEST);
        });
    }
    public static synchronized void fill(PlatformGraphics graphics,int x,int y,int w,int h) {
        if(w<=0||h<=0)return;
        Layer destination=layer(graphics.baseImage);flushDirty(destination);
        Rectangle clip=clip(graphics);
        int dx=x+graphics.translateX,dy=y+graphics.translateY,color=graphics.color;
        enqueue(() -> {
            target(destination);scissor(destination,clip);blend(true);glDisable(GL_TEXTURE_2D);
            float alpha=(color>>>24)/255f;
            glColor4f(((color>>16)&255)/255f*alpha,((color>>8)&255)/255f*alpha,(color&255)/255f*alpha,alpha);
            quad(dx*S,dy*S,w*S,h*S,0,0,1,1);glDisable(GL_SCISSOR_TEST);
        });
    }
    private static Rectangle clip(PlatformGraphics graphics) {
        Rectangle r=graphics.gc.getClipBounds();
        return new Rectangle(r.x+graphics.translateX,r.y+graphics.translateY,r.width,r.height);
    }
    public static synchronized void blit(PlatformGraphics graphics,PlatformImage image,int sx,int sy,int sw,int sh,
                                         int x,int y,int dw,int dh,int transform,boolean flush) {
        if(sw<=0||sh<=0||dw<=0||dh<=0||sx<0||sy<0||sx+sw>image.getWidth()||sy+sh>image.getHeight())return;
        Enhancement.ensureRequested(image);
        Layer source=layer(image),destination=layer(graphics.baseImage);
        flushDirty(source);if(source!=destination)flushDirty(destination);
        Rectangle clip=flush?new Rectangle(0,0,destination.w,destination.h):clip(graphics);
        int dx=x+(flush?0:graphics.translateX),dy=y+(flush?0:graphics.translateY);
        enqueue(() -> draw(source,destination,sx,sy,sw,sh,dx,dy,dw,dh,transform,flush,clip));
    }
    private static void draw(Layer source,Layer destination,int sx,int sy,int sw,int sh,int x,int y,int dw,int dh,int transform,boolean replace,Rectangle clip) {
        int texture=source.texture,temp=0;
        if(source==destination) {
            // Self-copy needs a separate source texture to avoid framebuffer feedback.
            target(source);temp=glGenTextures();glBindTexture(GL_TEXTURE_2D,temp);parameters();
            glCopyTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,0,0,source.w*S,source.h*S,0);texture=temp;
        }
        target(destination);scissor(destination,clip);blend(!replace);glEnable(GL_TEXTURE_2D);glColor4f(1,1,1,1);
        glBindTexture(GL_TEXTURE_2D,texture);
        float u0=(float)sx/source.w,u1=(float)(sx+sw)/source.w;
        float v0=1f-(float)sy/source.h,v1=1f-(float)(sy+sh)/source.h;
        // Destination TL,TR,BR,BL -> source corners for all eight MIDP transforms.
        int[] map=CORNERS[transform];
        glBegin(GL_QUADS);
        for(int i=0;i<4;i++) {
            int corner=map[i];
            glTexCoord2f(corner==0||corner==3?u0:u1,corner<2?v0:v1);
            glVertex2f((i==0||i==3?x:x+dw)*S,(i<2?y:y+dh)*S);
        }
        glEnd();glDisable(GL_SCISSOR_TEST);
        if(temp!=0)glDeleteTextures(temp);
    }
    public static synchronized void sync(PlatformImage image,int x,int y,int w,int h) {
        Layer destination=layer(image);flushDirty(destination);
        int left=Math.max(0,x),top=Math.max(0,y),right=Math.min(image.getWidth(),x+w),bottom=Math.min(image.getHeight(),y+h);
        if(right<=left||bottom<=top)return;
        int width=right-left,height=bottom-top;
        int[] pixels=image.getCanvas().getRGB(left,top,width,height,null,0,width);
        enqueue(() -> {
            target(destination);blend(false);glEnable(GL_TEXTURE_2D);glColor4f(1,1,1,1);
            int texture=glGenTextures();glBindTexture(GL_TEXTURE_2D,texture);parameters();upload(pixels,0,width,height);
            quad(left*S,top*S,width*S,height*S,0,0,1,1);glDeleteTextures(texture);
        });
    }
    public static void publish(PlatformImage image) {
        // Never wait for the GPU while holding its shared surface lock.
        if(closing||!FRAMES.acquire())return;
        synchronized(GpuRenderer.class) {
            if(closing){FRAMES.complete();return;}
            Layer result=layer(image);flushDirty(result);
            enqueue(() -> {try{commit(result);}finally{FRAMES.complete();}});
            RuntimeAssets.endFrame();
        }
    }
    private static void commit(Layer layer) {
        if(spare==null||spare.w!=layer.w||spare.h!=layer.h) {
            if(spare!=null)spare.destroy();spare=new Frame(layer.w,layer.h);
        }
        // Snapshot only at the frame boundary. Later queued writes must never alter
        // the texture currently being displayed when a pump budget expires.
        glBindFramebuffer(GL_READ_FRAMEBUFFER,layer.framebuffer);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,spare.framebuffer);
        glDisable(GL_SCISSOR_TEST);
        glBlitFramebuffer(0,0,layer.w*S,layer.h*S,0,0,layer.w*S,layer.h*S,GL_COLOR_BUFFER_BIT,GL_NEAREST);
        Frame old=presented;presented=spare;spare=old;boundFramebuffer=-1;submittedFrames++;
    }
    private static void create(Layer layer,BufferedImage initial) {
        layer.texture=glGenTextures();glBindTexture(GL_TEXTURE_2D,layer.texture);parameters();
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,layer.w*S,layer.h*S,0,GL_RGBA,GL_UNSIGNED_BYTE,(ByteBuffer)null);
        layer.framebuffer=glGenFramebuffers();glBindFramebuffer(GL_FRAMEBUFFER,layer.framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,layer.texture,0);
        if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw new IllegalStateException("GPU framebuffer is incomplete");
        ALLOCATED.add(layer);replace(layer,initial);
    }
    private static void replace(Layer layer,BufferedImage image) {
        if(S>1 && image.getWidth()==layer.w && image.getHeight()==layer.h &&
                FastTextureScaler.scale(image,layer.framebuffer,layer.w,layer.h,S)) return;
        target(layer);blend(false);glEnable(GL_TEXTURE_2D);glColor4f(1,1,1,1);
        int temp=glGenTextures();glBindTexture(GL_TEXTURE_2D,temp);parameters();
        if(layer.smoothFallback&&image.getWidth()==layer.w)glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        upload(image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth()),0,image.getWidth(),image.getHeight());
        quad(0,0,layer.w*S,layer.h*S,0,0,1,1);glDeleteTextures(temp);
    }
    static void bindScalerTarget(int framebuffer,int width,int height) {
        glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);boundFramebuffer=framebuffer;projection(width,height);
    }
    static void invalidateScalerBinding() { boundFramebuffer=-1; }
    private static void parameters() {
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    }
    private static void upload(int[] pixels,int offset,int w,int h) {
        ByteBuffer buffer=MemoryUtil.memAlloc(w*h*4);
        try {
            for(int i=0;i<w*h;i++) {
                int p=pixels[offset+i],a=p>>>24;
                buffer.put((byte)((((p>>16)&255)*a+127)/255));buffer.put((byte)((((p>>8)&255)*a+127)/255));
                buffer.put((byte)(((p&255)*a+127)/255));buffer.put((byte)a);
            }
            buffer.flip();glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,buffer);
        }finally{MemoryUtil.memFree(buffer);}
    }
    private static void target(Layer layer) {
        if(boundFramebuffer!=layer.framebuffer){glBindFramebuffer(GL_FRAMEBUFFER,layer.framebuffer);projection(layer.w*S,layer.h*S);boundFramebuffer=layer.framebuffer;}
        glDisable(GL_SCISSOR_TEST);
    }
    private static void projection(int w,int h) {
        glViewport(0,0,w,h);glMatrixMode(GL_PROJECTION);glLoadIdentity();glOrtho(0,w,h,0,-1,1);glMatrixMode(GL_MODELVIEW);glLoadIdentity();
    }
    private static void scissor(Layer layer,Rectangle clip) {
        Rectangle r=clip.intersection(new Rectangle(0,0,layer.w,layer.h));
        glEnable(GL_SCISSOR_TEST);glScissor(r.x*S,(layer.h-r.y-r.height)*S,Math.max(0,r.width*S),Math.max(0,r.height*S));
    }
    private static void blend(boolean enabled) {
        if(enabled){glEnable(GL_BLEND);glBlendFunc(GL_ONE,GL_ONE_MINUS_SRC_ALPHA);}else glDisable(GL_BLEND);
    }
    private static void quad(float x,float y,float w,float h,float u0,float v0,float u1,float v1) {
        glBegin(GL_QUADS);
        glTexCoord2f(u0,v0);glVertex2f(x,y);glTexCoord2f(u1,v0);glVertex2f(x+w,y);
        glTexCoord2f(u1,v1);glVertex2f(x+w,y+h);glTexCoord2f(u0,v1);glVertex2f(x,y+h);glEnd();
    }
    /** Drain within an input-poll budget; commands remain ordered across frames. */
    public static int pump(long budgetNanos) {
        long start=System.nanoTime();int count=0;Runnable command;
        while((command=QUEUE.poll())!=null){command.run();count++;if(System.nanoTime()-start>budgetNanos)break;}
        return count;
    }
    public static void drain() {while(pump(1000000000L)>0){} }
    public static void present(int width,int height) {
        glBindFramebuffer(GL_FRAMEBUFFER,0);boundFramebuffer=0;projection(width,height);glDisable(GL_SCISSOR_TEST);glDisable(GL_BLEND);
        glClearColor(.035f,.055f,.08f,1);glClear(GL_COLOR_BUFFER_BIT);
        Frame image=presented;
        if(image!=null) {
            float scale=Math.min((float)width/image.w,(float)height/image.h);
            float w=image.w*scale,h=image.h*scale;
            glEnable(GL_TEXTURE_2D);glBindTexture(GL_TEXTURE_2D,image.texture);
            int filter = S > 1 ? GL_LINEAR : GL_NEAREST;
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,filter);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,filter);
            glColor4f(1,1,1,1);quad((width-w)/2,(height-h)/2,w,h,0,1,1,0);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
        }
    }
    public static synchronized BufferedImage readback(PlatformImage image) {
        Layer layer=LAYERS.get(image);if(layer==null)throw new IllegalArgumentException("Image has no GPU surface");
        flushDirty(layer);drain();target(layer);
        ByteBuffer bytes=MemoryUtil.memAlloc(layer.w*S*layer.h*S*4);
        try {
            glReadPixels(0,0,layer.w*S,layer.h*S,GL_RGBA,GL_UNSIGNED_BYTE,bytes);
            BufferedImage result=new BufferedImage(layer.w*S,layer.h*S,BufferedImage.TYPE_INT_ARGB);
            for(int y=0;y<result.getHeight();y++)for(int x=0;x<result.getWidth();x++) {
                int p=((result.getHeight()-1-y)*result.getWidth()+x)*4;
                int a=bytes.get(p+3)&255,r=bytes.get(p)&255,g=bytes.get(p+1)&255,b=bytes.get(p+2)&255;
                if(a>0 && a<255){r=Math.min(255,(r*255+a/2)/a);g=Math.min(255,(g*255+a/2)/a);b=Math.min(255,(b*255+a/2)/a);}
                result.setRGB(x,y,(a<<24)|(r<<16)|(g<<8)|b);
            }
            return result;
        }finally{MemoryUtil.memFree(bytes);}
    }
    public static void cleanup() {
        if(!QUEUE.isEmpty())return;
        Iterator<Layer> it=ALLOCATED.iterator();
        while(it.hasNext()){Layer l=it.next();if(l.owner.get()==null){glDeleteTextures(l.texture);glDeleteFramebuffers(l.framebuffer);it.remove();}}
    }
    public static void shutdown(){closing=true;FRAMES.close();QUEUE.clear();for(Layer l:ALLOCATED){glDeleteTextures(l.texture);glDeleteFramebuffers(l.framebuffer);}ALLOCATED.clear();if(presented!=null)presented.destroy();if(spare!=null)spare.destroy();presented=null;spare=null;}
    public static long fastScalerPasses(){return FastTextureScaler.completedPasses();}
    public static long fastScalerFallbacks(){return FastTextureScaler.fallbackCount();}
    public static long fastScalerSubmitNanos(){return FastTextureScaler.lastSubmitNanos();}
    public static boolean warmupFastScaler(){return FastTextureScaler.warmup();}
}
