import org.recompile.mobile.*;
import java.util.*;
import java.util.concurrent.*;

public final class FramePipelineCheck {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        FramePresentationPolicy view=new FramePresentationPolicy();
        check(!view.shouldPresent(0,0,100),"Minimized windows must not swap");
        check(view.shouldPresent(0,100,100),"Initial picture");view.presenting(0,100,100);
        check(!view.shouldPresent(0,100,100),"Incomplete GPU work must not repeatedly swap the old picture");
        check(view.shouldPresent(1,100,100),"Completed frame");view.presenting(1,100,100);
        check(view.shouldPresent(1,200,100),"Resize");view.presenting(1,200,100);
        view.requestRedraw();check(view.shouldPresent(1,200,100),"OS expose");view.presenting(1,200,100);
        check(!view.shouldPresent(1,200,100),"Redraw request consumed");

        FrameBackpressure frames=new FrameBackpressure(2);
        check(frames.acquire()&&frames.acquire(),"Two in-flight frames allowed");
        FutureTask<Boolean> waiting=new FutureTask<Boolean>(()->frames.acquire());
        new Thread(waiting).start();
        try{waiting.get(80,TimeUnit.MILLISECONDS);throw new AssertionError("Frame capacity exceeded");}
        catch(TimeoutException expected){}
        frames.complete();check(waiting.get(500,TimeUnit.MILLISECONDS),"Completion releases producer");
        FutureTask<Boolean> closing=new FutureTask<Boolean>(()->frames.acquire());new Thread(closing).start();
        frames.close();check(!closing.get(500,TimeUnit.MILLISECONDS),"Shutdown releases waiting producer");

        int width=8;int[] pixels=new int[width*5];BitSet dirty=new BitSet();
        for(int i:new int[]{9,11,12,24,25,26,27,28,29,30,31}){dirty.set(i);pixels[i]=0x80000000|i;}
        BitSet expected=(BitSet)dirty.clone();PixelUploadBatch batch=PixelUploadBatch.capture(dirty,pixels,width);
        check(dirty.isEmpty(),"Dirty bits consumed");Arrays.fill(pixels,0);
        BitSet covered=new BitSet();
        for(int[] r:batch.regions)for(int y=r[1];y<r[1]+r[3];y++)for(int x=r[0];x<r[0]+r[2];x++) {
            int index=y*width+x;covered.set(index);
            check(batch.pixels[(y-batch.top)*width+x]==(0x80000000|index),"Snapshot and alpha preserved");
        }
        check(covered.equals(expected),"Sparse upload regions must preserve all untouched HD pixels");
        System.out.println("PASS: completed-frame scheduling, bounded backlog, shutdown and sparse pixel snapshots");
    }
}
