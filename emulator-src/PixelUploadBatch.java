/* Snapshot dirty pixels once; preserve holes so HD pixels outside the writes survive. GPL-3.0-or-later. */
package org.recompile.mobile;
import java.util.*;

public final class PixelUploadBatch {
    public final int top,height,width;
    public final int[] pixels;
    public final List<int[]> regions;
    private PixelUploadBatch(int top,int height,int width,int[] pixels,List<int[]> regions) {
        this.top=top;this.height=height;this.width=width;this.pixels=pixels;this.regions=regions;
    }
    public static PixelUploadBatch capture(BitSet dirty,int[] pending,int width) {
        if(dirty.isEmpty())throw new IllegalArgumentException("No dirty pixels");
        int top=dirty.nextSetBit(0)/width,bottom=(dirty.length()-1)/width+1;
        int[] pixels=Arrays.copyOfRange(pending,top*width,bottom*width);
        List<int[]> regions=new ArrayList<int[]>();
        for(int index=dirty.nextSetBit(0);index>=0;) {
            int end=Math.min(dirty.nextClearBit(index),((index/width)+1)*width);
            int columns=end-index,rows=1;
            if(index%width==0&&columns==width) {
                while(end+width<=pending.length&&dirty.nextClearBit(end)>=end+width){end+=width;rows++;}
            }
            regions.add(new int[]{index%width,index/width,columns,rows});
            index=dirty.nextSetBit(end);
        }
        dirty.clear();return new PixelUploadBatch(top,bottom-top,width,pixels,regions);
    }
}
