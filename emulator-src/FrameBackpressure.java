/* Bound queued frames independently of input handling or drawing commands. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

public final class FrameBackpressure {
    private final Semaphore slots;
    private volatile boolean closed;
    public FrameBackpressure(int capacity) {
        if(capacity<1)throw new IllegalArgumentException("Frame capacity must be positive");
        slots=new Semaphore(capacity,true);
    }
    public boolean acquire() {
        try {
            while(!closed)if(slots.tryAcquire(50,TimeUnit.MILLISECONDS))return !closed;
        }catch(InterruptedException error){Thread.currentThread().interrupt();}
        return false;
    }
    public void complete(){slots.release();}
    public void close(){closed=true;}
}
