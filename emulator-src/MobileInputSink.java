/* Emulator adapter and narrowly scoped release policy. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.util.*;
import javax.microedition.lcdui.*;

public final class MobileInputSink implements KeyInputController.Sink {
    private final Set<String> resetCanvases;
    private final CanvasStatePolicy statePolicy;
    public MobileInputSink(){this(System.getProperty("jme.input.restoreCanvases",""),System.getProperty("jme.input.restoreState",""));}
    public MobileInputSink(String classes){this(classes,"");}
    public MobileInputSink(String classes,String stateRule){resetCanvases=new HashSet<String>(Arrays.asList(classes.split(",")));statePolicy=new CanvasStatePolicy(stateRule);}
    public void press(int key){MobilePlatform.keyPressed(key);}
    public void release(int key){MobilePlatform.keyReleased(key);}
    public void repeat(int key){MobilePlatform.keyRepeated(key);}
    public boolean restoreMovementAfterRelease() {
        Displayable current=Mobile.getDisplay()==null?null:Mobile.getDisplay().getCurrent();
        return current instanceof Canvas&&resetCanvases.contains(current.getClass().getName())&&statePolicy.allows(current);
    }
}
