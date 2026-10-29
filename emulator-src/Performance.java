/* Local player telemetry only. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;

public final class Performance {
    private static final String PATH=System.getProperty("jme.stats");
    private static final ExecutorService WRITER=Executors.newSingleThreadExecutor(r -> {Thread t=new Thread(r,"local-frame-stats");t.setDaemon(true);return t;});
    private static long last=0, window=System.nanoTime();
    private static final long[] frames=new long[120], inputs=new long[64];
    private static int fi=0,fc=0,ii=0,ic=0,count=0;
    public static synchronized void input(long queued) {
        if(PATH==null)return;
        inputs[ii++%inputs.length]=System.nanoTime()-queued;ic=Math.min(ic+1,inputs.length);
    }
    private static double percentile(long[] data,int size) {
        if(size==0)return 0;
        long[] copy=Arrays.copyOf(data,size);Arrays.sort(copy);return copy[Math.min(size-1,(int)(size*.95))]/1e6;
    }
    public static synchronized void frame() {
        if(PATH==null)return;
        long now=System.nanoTime();
        if(last!=0) {frames[fi++%frames.length]=now-last;fc=Math.min(fc+1,frames.length);}
        last=now;count++;
        if(now-window<1000000000L)return;
        String json=String.format(Locale.US,"{\"fps\":%.2f,\"frame_p95_ms\":%.2f,\"input_queue_p95_ms\":%.2f,\"fast_scaler_submit_ms\":%.3f,\"gpu_scale_passes\":%d,\"gpu_scale_fallbacks\":%d,\"raw_rgb_gpu_draws\":%d,\"scale\":%d,\"backend\":\"%s\",\"updated\":%.3f}",
            count*1e9/(now-window),percentile(frames,fc),percentile(inputs,ic),
            Boolean.getBoolean("jme.gpu")?GpuRenderer.fastScalerSubmitNanos()/1e6:0.0,
            Boolean.getBoolean("jme.gpu")?GpuRenderer.fastScalerPasses():0L,
            Boolean.getBoolean("jme.gpu")?GpuRenderer.fastScalerFallbacks():0L,
            RawRgbPresentation.submittedDraws(),
            Enhancement.SCALE,Boolean.getBoolean("jme.gpu")?"OpenGL GPU":"Java2D CPU",System.currentTimeMillis()/1000.0);
        window=now;count=0;
        WRITER.execute(() -> {try {
            Path destination=Paths.get(PATH), temp=Paths.get(PATH+".tmp");
            Files.write(temp,json.getBytes(StandardCharsets.UTF_8));Files.move(temp,destination,StandardCopyOption.REPLACE_EXISTING);
        }catch(Exception e){System.err.println("Local performance report: "+e);}});
    }
}
