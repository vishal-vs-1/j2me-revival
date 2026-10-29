import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import javax.imageio.ImageIO;
import javax.microedition.lcdui.Image;
import javax.microedition.lcdui.game.Sprite;
import org.recompile.mobile.Enhancement;
import org.recompile.mobile.PlatformImage;
import org.recompile.mobile.RuntimeAssets;

/** Verifies async ready-cache lookup, frame-boundary replacement and stale revision rejection. */
public final class RuntimeTextureCheck {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static String repeated(char value, int count) {
        StringBuilder result = new StringBuilder(count);
        for (int i = 0; i < count; i++) result.append(value);
        return result.toString();
    }

    private static void writeReady(Path root, String recipe, String source, int width, int height, int generation) throws Exception {
        Path output = root.resolve("textures-cache").resolve(recipe);
        Files.createDirectories(output);
        BufferedImage hd = new BufferedImage(width * 4, height * 4, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < hd.getHeight(); y++) for (int x = 0; x < hd.getWidth(); x++)
            hd.setRGB(x, y, 0xff000000 | (x < hd.getWidth()/2 ? 0x00ee22 : 0x2211ee));
        ImageIO.write(hd, "PNG", output.resolve(source + ".png").toFile());
        Path manifest = root.resolve(".runtime").resolve("ready").resolve(recipe + ".json");
        Files.createDirectories(manifest.getParent());
        String json = "{\"schema\":1,\"generation\":" + generation + ",\"recipe_key\":\"" + recipe +
                "\",\"scale\":4,\"sources\":[\"" + source + "\"]}";
        Files.write(manifest, json.getBytes(StandardCharsets.UTF_8));
    }

    private static void waitForUpdate() throws Exception {
        long until = System.nanoTime() + 10_000_000_000L;
        while (RuntimeAssets.pendingTextureUpdates() == 0 && System.nanoTime() < until) Thread.sleep(10L);
        check(RuntimeAssets.pendingTextureUpdates() > 0, "ready texture was not queued asynchronously");
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory(Paths.get(args[0]), "runtime-texture-");
        String recipe = repeated('a', 64);
        System.setProperty("java.awt.headless", "true");
        System.setProperty("jme.pack", root.toString());
        System.setProperty("jme.scale", "2");
        System.setProperty("jme.recipeKey", recipe);

        int[] pixels = {0xff112233, 0xff334455, 0xff556677, 0xff778899};
        BufferedImage logical = new BufferedImage(2, 2, BufferedImage.TYPE_INT_ARGB);
        logical.setRGB(0, 0, 2, 2, pixels, 0, 2);
        String sourceId = Enhancement.hash(logical);
        writeReady(root, recipe, sourceId, 2, 2, 1);

        PlatformImage image = new PlatformImage(pixels, 2, 2, true);
        int[] before = image.getCanvas().getRGB(0, 0, 2, 2, null, 0, 2);
        Enhancement.surface(image);
        waitForUpdate();
        RuntimeAssets.endFrame();
        check(image.hdResolvedRecipe.equals(recipe), "ready recipe was not committed");
        check(image.hdCanvas != null && image.hdCanvas.getWidth() == 4 && image.hdCanvas.getHeight() == 4,
                "cache texture was not adapted to the selected render scale");
        check(image.hdCanvas.getRGB(0, 0) == 0xff00ee22, "cached texture did not replace the fallback presentation");
        check(java.util.Arrays.equals(before, image.getCanvas().getRGB(0, 0, 2, 2, null, 0, 2)),
                "replacement changed native game pixels");

        int[] parentPixels = {0xff100000, 0xff200000, 0xff300000,
                0xff001000, 0xff002000, 0xff003000};
        BufferedImage parentLogical = new BufferedImage(3, 2, BufferedImage.TYPE_INT_ARGB);
        parentLogical.setRGB(0, 0, 3, 2, parentPixels, 0, 3);
        String parentId = Enhancement.hash(parentLogical);
        writeReady(root, recipe, parentId, 3, 2, 22);
        Image parent = Image.createRGBImage(parentPixels, 3, 2, true);
        Image child = Image.createImage(parent, 1, 0, 2, 2, Sprite.TRANS_NONE);
        PlatformImage platformChild = (PlatformImage) child;
        BufferedImage childBefore = platformChild.hdCanvas;
        Enhancement.surface((PlatformImage) parent);
        waitForUpdate();
        RuntimeAssets.endFrame();
        check(platformChild.hdCanvas != childBefore,
                "a cached parent replacement was not propagated to its immutable crop");

        writeReady(root, recipe, sourceId, 2, 2, 333);
        PlatformImage stale = new PlatformImage(pixels, 2, 2, true);
        Enhancement.surface(stale);
        waitForUpdate();
        stale.hdCanvas = null;
        stale.setMutable(true);
        RuntimeAssets.beginMutation(stale);
        RuntimeAssets.endFrame();
        check(stale.hdResolvedRecipe == null && stale.hdCanvas == null,
                "a stale enhanced texture was bound after mutation began");
        RuntimeAssets.close();
        System.out.println("PASS: asynchronous cache lookup staged at a frame boundary; native pixels and stale revisions are protected");
    }
}
