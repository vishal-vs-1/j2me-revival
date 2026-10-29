/* JAR Revival additions, GPL-3.0-or-later. Original game pixels remain authoritative. */
package org.recompile.mobile;

import java.awt.AlphaComposite;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.awt.image.DataBufferInt;
import java.awt.geom.AffineTransform;
import java.io.File;
import java.lang.ref.WeakReference;
import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.*;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import javax.imageio.ImageIO;

public final class Enhancement {
    public static final int SCALE = Math.max(1, Math.min(4, Integer.getInteger("jme.scale", 1)));
    private static final File PACK = new File(System.getProperty("jme.pack", "."));
    private static final ScheduledThreadPoolExecutor IO = new ScheduledThreadPoolExecutor(1, r -> {
        Thread t = new Thread(r, "enhanced-asset-io"); t.setDaemon(true); return t;
    });
    static { IO.setRemoveOnCancelPolicy(true); }
    private static final LinkedHashMap<String,BufferedImage> DECODED=new LinkedHashMap<String,BufferedImage>(32,.75f,true);
    private static long decodedBytes=0;
    private static final long CACHE_BYTES=128L*1024*1024;
    /** Decode a bounded warm cache before game startup, avoiding texture changes mid-animation. */
    public static void preload() {
        if(SCALE==1)return;
        for(File directory:new File[]{new File(PACK,"textures-ui"),new File(System.getProperty("jme.textures",new File(PACK,"textures").getPath()))}) {
            File[] files=directory.listFiles((dir,name)->name.endsWith(".png"));if(files==null)continue;
            Arrays.sort(files);
            for(File file:files) {
                try {decode(file);}catch(Exception error){System.err.println("Artwork preload: "+error);}
                if(decodedBytes>=CACHE_BYTES*3/4)break;
            }
        }
    }

    public static BufferedImage surface(PlatformImage image) {
        RuntimeAssets.usedAsSource(image);
        if(GpuRenderer.ENABLED) {ensureRequested(image);GpuRenderer.observe(image);return image.getCanvas();}
        if (SCALE == 1) return image.getCanvas();
        BufferedImage result = image.hdCanvas;
        if (result == null) synchronized(image) {
            result = image.hdCanvas;
            if (result == null) {
                if ((long)image.getWidth() * image.getHeight() > 4194304L)
                    return image.getCanvas();
                result = new BufferedImage(image.getWidth()*SCALE, image.getHeight()*SCALE, BufferedImage.TYPE_INT_ARGB);
                Graphics2D g = result.createGraphics();
                g.setComposite(AlphaComposite.Src);
                g.drawImage(image.getCanvas(), 0, 0, result.getWidth(), result.getHeight(), null);
                g.dispose();
                image.hdCanvas = result;
                if (!image.isMutable()) {image.hdRequested=true;request(image);}
            }
        }
        return result;
    }

    public static void ensureRequested(PlatformImage image) {
        RuntimeAssets.usedAsSource(image);
        if(SCALE==1||image.isMutable()||image.hdRequested)return;
        synchronized(image) {if(!image.hdRequested){image.hdRequested=true;request(image);}}
    }

    public static void derive(PlatformImage image,PlatformImage source,int x,int y,int w,int h,int transform) {
        image.hdGenerated=true;
        RuntimeAssets.derived(image,source,x,y,w,h,transform);
        if(SCALE==1)return;
        ensureRequested(source);
        if(GpuRenderer.ENABLED){GpuRenderer.derive(image,source,x,y,w,h,transform);return;}
        BufferedImage original=surface(source);
        image.hdCanvas=PlatformImage.transformImage(copy(original.getSubimage(x*SCALE,y*SCALE,w*SCALE,h*SCALE)),transform);
    }

    private static void request(PlatformImage image) {
        try {
                String id = hash(image.getCanvas());
                File ui=new File(new File(PACK,"textures-ui"),id+".png");
                if(load(image,ui))return;
                File texture = new File(new File(System.getProperty("jme.textures", new File(PACK,"textures").getPath())), id+".png");
                if(load(image,texture))return;
        }catch(Exception error){System.err.println("Enhancement lookup: "+error);}
    }

    private static boolean load(PlatformImage image, File file) throws Exception {
        if (!file.isFile()) return false;
        BufferedImage decoded = decode(file);
        if (decoded == null || decoded.getWidth() != image.getWidth()*4 || decoded.getHeight() != image.getHeight()*4)
            return false;
        if(SCALE==4){image.hdCanvas=decoded;System.out.println("Enhanced asset loaded: "+file.getName());return true;}
        BufferedImage argb = new BufferedImage(image.getWidth()*SCALE, image.getHeight()*SCALE, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = argb.createGraphics(); g.setComposite(AlphaComposite.Src);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(decoded, 0, 0, argb.getWidth(), argb.getHeight(), null); g.dispose();
        image.hdCanvas = argb;
        System.out.println("Enhanced asset loaded: "+file.getName());
        return true;
    }
    private static synchronized BufferedImage decode(File file)throws Exception {
        BufferedImage cached=DECODED.get(file.getAbsolutePath());if(cached!=null)return cached;
        BufferedImage image=ImageIO.read(file);if(image==null)return null;
        long bytes=(long)image.getWidth()*image.getHeight()*4;
        if(bytes>CACHE_BYTES)return image;
        while(decodedBytes+bytes>CACHE_BYTES&&!DECODED.isEmpty()) {
            Iterator<BufferedImage> it=DECODED.values().iterator();BufferedImage old=it.next();it.remove();
            decodedBytes-=(long)old.getWidth()*old.getHeight()*4;
        }
        DECODED.put(file.getAbsolutePath(),image);decodedBytes+=bytes;return image;
    }

    public static String hash(BufferedImage image) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        digest.update(ByteBuffer.allocate(8).putInt(image.getWidth()).putInt(image.getHeight()).array());
        int[] pixels = image.getRGB(0, 0, image.getWidth(), image.getHeight(), null, 0, image.getWidth());
        for (int p : pixels) {
            if ((p >>> 24) == 0) p = 0;
            digest.update((byte)(p>>16)); digest.update((byte)(p>>8)); digest.update((byte)p); digest.update((byte)(p>>>24));
        }
        StringBuilder result = new StringBuilder();
        for (byte b : digest.digest()) result.append(String.format("%02x", b & 255));
        return result.toString();
    }

    public static void pixel(PlatformImage image, int index, int value) {
        if(GpuRenderer.ENABLED) {
            if(!image.getCanvas().getColorModel().hasAlpha())value|=0xff000000;
            GpuRenderer.pixel(image,index,value);return;
        }
        BufferedImage hd = image.hdCanvas;
        if (SCALE == 1 || hd == null) return;
        // TYPE_INT_RGB stores glyph pixels without alpha bits, although they are opaque.
        if (!image.getCanvas().getColorModel().hasAlpha()) value |= 0xFF000000;
        int width = image.getWidth(), x = index % width, y = index / width;
        int[] data = ((DataBufferInt)hd.getRaster().getDataBuffer()).getData();
        for (int row = 0; row < SCALE; row++) {
            int start = (y*SCALE+row)*hd.getWidth()+x*SCALE;
            Arrays.fill(data, start, start+SCALE, value);
        }
    }

    public static void sync(PlatformImage image, int x, int y, int width, int height) {
        if(GpuRenderer.ENABLED){GpuRenderer.sync(image,x,y,width,height);return;}
        if (SCALE == 1) return;
        BufferedImage hd = surface(image);
        int left = Math.max(0, x), top = Math.max(0, y);
        int right = Math.min(image.getWidth(), x+width), bottom = Math.min(image.getHeight(), y+height);
        if (right <= left || bottom <= top) return;
        Graphics2D g = hd.createGraphics();
        g.setComposite(AlphaComposite.Src);
        g.drawImage(image.getCanvas(), left*SCALE, top*SCALE, right*SCALE, bottom*SCALE, left, top, right, bottom, null);
        g.dispose();
    }

    public static void blit(PlatformGraphics target, PlatformImage source, int sx, int sy, int sw, int sh,
                            int x, int y, int dw, int dh, int midpTransform, boolean flush) {
        if(GpuRenderer.ENABLED){GpuRenderer.blit(target,source,sx,sy,sw,sh,x,y,dw,dh,midpTransform,flush);return;}
        if (SCALE == 1 || source == null || sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) return;
        try {
            BufferedImage hd = surface(target.baseImage), src = surface(source);
            if (sx < 0 || sy < 0 || sx+sw > source.getWidth() || sy+sh > source.getHeight()) return;
            BufferedImage region = src.getSubimage(sx*SCALE, sy*SCALE, sw*SCALE, sh*SCALE);
            if (source == target.baseImage) region = copy(region);
            Graphics2D g = hd.createGraphics();
            if (flush) g.setComposite(AlphaComposite.Src);
            else {
                Rectangle clip = target.gc.getClipBounds();
                g.setClip((clip.x+target.translateX)*SCALE, (clip.y+target.translateY)*SCALE, clip.width*SCALE, clip.height*SCALE);
                x += target.translateX; y += target.translateY;
            }
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
            int w=region.getWidth(), h=region.getHeight();
            boolean rotated=midpTransform>=4;
            g.translate(x*SCALE,y*SCALE);
            g.scale((double)dw*SCALE/(rotated?h:w),(double)dh*SCALE/(rotated?w:h));
            switch(midpTransform) {
                case 1: g.transform(new AffineTransform(1,0,0,-1,0,h)); break;
                case 2: g.transform(new AffineTransform(-1,0,0,1,w,0)); break;
                case 3: g.transform(new AffineTransform(-1,0,0,-1,w,h)); break;
                case 4: g.transform(new AffineTransform(0,1,1,0,0,0)); break;
                case 5: g.transform(new AffineTransform(0,1,-1,0,h,0)); break;
                case 6: g.transform(new AffineTransform(0,-1,1,0,0,w)); break;
                case 7: g.transform(new AffineTransform(0,-1,-1,0,h,w)); break;
            }
            g.drawImage(region,0,0,null);
            g.dispose();
        } catch (Exception error) {
            sync(target.baseImage, 0, 0, target.canvasWidth, target.canvasHeight);
            System.err.println("Enhancement drawing fallback: "+error);
        }
    }

    public static void fill(PlatformGraphics target,int x,int y,int width,int height) {
        if(GpuRenderer.ENABLED){GpuRenderer.fill(target,x,y,width,height);return;}
        if(SCALE==1 || width<=0 || height<=0)return;
        Graphics2D g=surface(target.baseImage).createGraphics();
        Rectangle clip=target.gc.getClipBounds();
        g.setClip((clip.x+target.translateX)*SCALE,(clip.y+target.translateY)*SCALE,clip.width*SCALE,clip.height*SCALE);
        g.setColor(new java.awt.Color(target.color,true));
        g.fillRect((x+target.translateX)*SCALE,(y+target.translateY)*SCALE,width*SCALE,height*SCALE);
        g.dispose();
    }

    private static BufferedImage copy(BufferedImage source) {
        BufferedImage result = new BufferedImage(source.getWidth(), source.getHeight(), BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = result.createGraphics(); g.setComposite(AlphaComposite.Src); g.drawImage(source, 0, 0, null); g.dispose();
        return result;
    }

    private static int proofFrames = 0;
    public static void frame(PlatformImage image) {
        Performance.frame();
        if(GpuRenderer.ENABLED){GpuRenderer.publish(image);return;}
        RuntimeAssets.endFrame();
        String output = System.getProperty("jme.proof");
        if (output != null && ++proofFrames == 120) {
            BufferedImage snapshot = copy(surface(image));
            IO.execute(() -> {
                try { ImageIO.write(snapshot,"PNG",new File(output)); System.out.println("PROOF: 120 enhanced frames rendered"); }
                catch(Exception e) { e.printStackTrace(); }
            });
        }
    }

    public static void text(PlatformGraphics target, String text, int x, int y) {
        if (SCALE == 1 && !GpuRenderer.ENABLED) return;
        // Keep original advances and rasterization; copy only covered glyph pixels.
        Rectangle bounds=target.gc.getFont().getStringBounds(text,target.gc.getFontRenderContext()).getBounds();
        bounds.translate(x+target.translateX,y+target.translateY); bounds.grow(2,2);
        bounds=bounds.intersection(new Rectangle(0,0,target.canvasWidth,target.canvasHeight));
        if(bounds.isEmpty())return;
        if(GpuRenderer.ENABLED) {
            BufferedImage smooth=new BufferedImage(bounds.width*SCALE,bounds.height*SCALE,BufferedImage.TYPE_INT_ARGB);
            Graphics2D g=smooth.createGraphics();g.scale(SCALE,SCALE);
            g.translate(target.translateX-bounds.x,target.translateY-bounds.y);g.setClip(target.gc.getClip());
            g.setFont(target.gc.getFont());g.setColor(target.gc.getColor());
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            g.drawString(text,x,y);g.dispose();
            GpuRenderer.textPatch(target,bounds.x,bounds.y,bounds.width,bounds.height,
                ((DataBufferInt)smooth.getRaster().getDataBuffer()).getData(),SCALE);return;
        }
        BufferedImage mask = new BufferedImage(bounds.width,bounds.height, BufferedImage.TYPE_INT_ARGB);
        Graphics2D m = mask.createGraphics();
        m.translate(target.translateX-bounds.x,target.translateY-bounds.y); m.setClip(target.gc.getClip());
        m.setFont(target.gc.getFont()); m.setColor(java.awt.Color.WHITE);
        m.setRenderingHints(target.gc.getRenderingHints()); m.drawString(text, x, y); m.dispose();
        int[] alpha = ((DataBufferInt)mask.getRaster().getDataBuffer()).getData();
        surface(target.baseImage);
        if(GpuRenderer.ENABLED&&!target.baseImage.getCanvas().getColorModel().hasAlpha()) {
            int[] pixels=new int[alpha.length];
            for(int yy=0;yy<bounds.height;yy++)for(int xx=0;xx<bounds.width;xx++) {
                int p=yy*bounds.width+xx;
                if((alpha[p]>>>24)!=0)pixels[p]=0xff000000|target.canvasData[(yy+bounds.y)*target.canvasWidth+xx+bounds.x];
            }
            GpuRenderer.textPatch(target,bounds.x,bounds.y,bounds.width,bounds.height,pixels,1);return;
        }
        for (int yy=0;yy<bounds.height;yy++)for(int xx=0;xx<bounds.width;xx++) {
            if((alpha[yy*bounds.width+xx]>>>24)!=0) {
                int i=(yy+bounds.y)*target.canvasWidth+xx+bounds.x;
                pixel(target.baseImage,i,target.canvasData[i]);
            }
        }
    }
}
