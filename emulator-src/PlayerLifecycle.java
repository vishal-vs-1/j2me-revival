/* Bounded game shutdown: broken wrappers must not turn a window close into a renderer failure. */
package org.recompile.mobile;
import javax.microedition.midlet.MIDlet;

public final class PlayerLifecycle {
    public static void stop(final MIDlet game,long timeoutMillis) {
        if(game==null)return;
        Thread close=new Thread(()->{
            try {game.requestDestroy(true);}
            catch(Throwable error){System.err.println("Game shutdown callback failed: "+error.getClass().getSimpleName());}
        },"game-shutdown");
        close.setDaemon(true);close.start();
        try {close.join(Math.max(1,timeoutMillis));}
        catch(InterruptedException error){Thread.currentThread().interrupt();}
        if(close.isAlive())System.err.println("Game shutdown callback timed out; closing its process.");
    }
}
