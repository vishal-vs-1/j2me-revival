/* Desktop keyboard translation only. GPL-3.0-or-later. */
package org.recompile.mobile;
import static org.lwjgl.glfw.GLFW.*;

public final class DesktopKeyMap {
    public static final int UNMAPPED=Integer.MIN_VALUE;
    public static int toPhone(int key) {
        switch(key) {
            case GLFW_KEY_UP:return -1;case GLFW_KEY_DOWN:return -2;
            case GLFW_KEY_LEFT:return -3;case GLFW_KEY_RIGHT:return -4;
            case GLFW_KEY_ENTER:case GLFW_KEY_KP_ENTER:return -5;
            case GLFW_KEY_Q:return -6;case GLFW_KEY_W:return -7;
            case GLFW_KEY_E:return 42;case GLFW_KEY_R:return 35;
        }
        if(key>=GLFW_KEY_0&&key<=GLFW_KEY_9)return 48+key-GLFW_KEY_0;
        if(key>=GLFW_KEY_KP_0&&key<=GLFW_KEY_KP_9)return 48+key-GLFW_KEY_KP_0;
        return UNMAPPED;
    }
}
