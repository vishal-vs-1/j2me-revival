/* Optional exact-game state gate for held-key restoration. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.lang.reflect.Field;
import javax.microedition.lcdui.Displayable;

public final class CanvasStatePolicy {
    private final String canvasName,fieldName;
    private final int requiredState;
    private Field stateField;
    public CanvasStatePolicy(String rule) {
        if(rule==null||rule.isEmpty()){canvasName=null;fieldName=null;requiredState=0;return;}
        String[] parts=rule.split(":",-1);
        if(parts.length!=3||parts[0].isEmpty()||parts[1].isEmpty())throw new IllegalArgumentException("Bad canvas state rule");
        canvasName=parts[0];fieldName=parts[1];requiredState=Integer.parseInt(parts[2]);
    }
    public boolean allows(Displayable current) {
        if(canvasName==null)return true;
        if(current==null||!current.getClass().getName().equals(canvasName))return false;
        try {
            if(stateField==null){stateField=current.getClass().getDeclaredField(fieldName);stateField.setAccessible(true);}
            return stateField.getInt(null)==requiredState;
        }catch(ReflectiveOperationException|SecurityException error){return false;}
    }
}
