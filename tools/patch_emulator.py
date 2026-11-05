"""Reproducible source hooks for the pinned FreeJ2ME-Plus revision."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/freej2me-plus/src/org/recompile'


def normalize_generated_hooks(text):
    """Remove obsolete probes and collapse hooks emitted by older patcher builds."""
    text = re.sub(r'(?m)^[ \t]*DecodedAssetCapture\.(?:capture|resource)\([^;]*;[ \t]*\r?\n', '', text)
    text = re.sub(r'(?m)^[ \t]*Enhancement\.promoteDecoded\(this\);[ \t]*\r?\n', '', text)
    hooks = {
        'RuntimeAssets.created(this, ImageObservation.SourceKind.ENCODED);',
        'RuntimeAssets.created(this, ImageObservation.SourceKind.RGB);',
        'RuntimeAssets.created(this, ImageObservation.SourceKind.RESOURCE);',
        'RuntimeAssets.created(this, ImageObservation.SourceKind.MUTABLE_SNAPSHOT, ImageObservation.SurfaceRole.OFFSCREEN);',
    }
    lines = text.splitlines(True)
    output = []
    previous_hook = None
    for line in lines:
        stripped = line.strip()
        if stripped in hooks:
            if stripped == previous_hook:
                continue
            previous_hook = stripped
            output.append(line)
        else:
            if stripped:
                previous_hook = None
            output.append(line)
    return ''.join(output)


def wrap_public_method(text, signature, mutation_target, suppress_raw=True, post=None):
    """Add one nested-safe mutation boundary around a shared emulator draw API."""
    match = re.search(r'public void ' + signature + r'\s*\{', text)
    if not match:
        return text
    declaration = match[0][:-1].strip()
    name = re.search(r'public void (\w+)', declaration).group(1)
    start = match.start()
    opening = text.index('{', match.start())
    if text[opening + 1:opening + 100].find('// Runtime mutation boundary') >= 0:
        return text
    depth = 1
    end = opening + 1
    while depth:
        if text[end] == '{': depth += 1
        elif text[end] == '}': depth -= 1
        end += 1
    params = declaration[declaration.index('(') + 1:declaration.rindex(')')]
    args = ', '.join(part.strip().split()[-1] for part in params.split(',') if part.strip())
    original_name = 'hdMutationOriginal_' + name
    original_header = text[start:opening].replace('public void ' + name,
                                                   'private void ' + original_name, 1)
    original = original_header + text[opening:end]
    wrapper = declaration + ''' {
        // Runtime mutation boundary; nested drawing helpers share one revision.
        RuntimeAssets.beginMutation(''' + mutation_target + ''');
        try {
            ''' + ('hdRawRgbSuppression++;\n            try { ' if suppress_raw else '') + original_name + '(' + args + ');' + ('' if post is None else '\n            ' + post) + ('''\n            } finally { hdRawRgbSuppression--; }''' if suppress_raw else '') + '''
        } finally { RuntimeAssets.endMutation(''' + mutation_target + '''); }
    }
'''
    text = text[:start] + original + text[end:]
    return text[:text.rfind('}')] + wrapper + text[text.rfind('}'):]


def patch():
    patch_m3g()
    image = SOURCE / 'mobile/PlatformImage.java'
    text = normalize_generated_hooks(image.read_text(encoding='utf-8'))
    if 'hdRequested' not in text:
        text=text.replace('public class PlatformImage\n{','public class PlatformImage\n{\n    public volatile boolean hdRequested;\n    public volatile boolean hdCaptureObserved;\n    public volatile long hdCaptureRetryAfter;')
    elif 'hdCaptureObserved' not in text:
        text=text.replace('public volatile boolean hdRequested;','public volatile boolean hdRequested;\n    public volatile boolean hdCaptureObserved;\n    public volatile long hdCaptureRetryAfter;')
    if 'hdSourceId' not in text:
        text=text.replace('public volatile long hdCaptureRetryAfter;','public volatile long hdCaptureRetryAfter;\n    public volatile String hdSourceId;\n    public volatile String hdResolvedRecipe;\n    public volatile boolean hdLookupPending;')
    if 'hdCanvas' not in text:
        text = text.replace('protected BufferedImage canvas;', 'protected BufferedImage canvas;\n\tpublic volatile BufferedImage hdCanvas;')
        # Direct pixel changes must invalidate the corresponding presentation pixel.
        text = text.replace('dataBuffer[y * canvas.getWidth() + x] = color;', 'dataBuffer[y * canvas.getWidth() + x] = color;\n        Enhancement.pixel(this, y * canvas.getWidth() + x, color);')
        image.write_text(text, encoding='utf-8')
    image.write_text(text,encoding='utf-8')
    if 'hdGenerated' not in text:
        text=text.replace('public volatile boolean hdRequested;','public volatile boolean hdRequested;\n    public boolean hdGenerated;')
        def constructor_hook(signature,code):
            nonlocal text
            start=text.index('{',text.index(signature));end=start+1;depth=1
            while depth:
                if text[end]=='{':depth+=1
                elif text[end]=='}':depth-=1
                end+=1
            text=text[:end-1]+code+'\n\t'+text[end-1:]
        constructor_hook('public PlatformImage(int[] rgb, int Width, int Height, boolean processAlpha)',
                         '\n        hdGenerated=true; // Transient, generated pixel data is never an AI discovery candidate.\n')
        constructor_hook('public PlatformImage(Image source)',
                         '\n        Enhancement.derive(this,source,0,0,source.getWidth(),source.getHeight(),0);\n')
        constructor_hook('public PlatformImage(Image image, int x, int y, int Width, int Height, int transform)',
                         '\n        Enhancement.derive(this,image,x,y,Width,Height,transform);\n')
        image.write_text(text,encoding='utf-8')
    text = re.sub(r'(?m)^\s*public boolean hdTransient;\s*\r?\n', '', text)
    text = re.sub(r'(?m)^\s*hdTransient\s*=\s*true;[^\r\n]*\r?\n', '', text)
    def append_constructor_hook(signature, statement):
        nonlocal text
        sig=text.index(signature)
        start=text.index('{',sig)
        end=start+1
        depth=1
        while depth:
            if text[end]=='{': depth+=1
            elif text[end]=='}': depth-=1
            end+=1
        body=text[start:end]
        if statement not in body:
            text=text[:end-1]+'\n        '+statement+'\n\t'+text[end-1:]
    append_constructor_hook('public PlatformImage(String name)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.RESOURCE);')
    append_constructor_hook('public PlatformImage(InputStream stream)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.RESOURCE);')
    append_constructor_hook('public PlatformImage(byte[] imageData, int imageOffset, int imageLength, boolean mutable)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.ENCODED);')
    append_constructor_hook('public PlatformImage(int[] rgb, int Width, int Height, boolean processAlpha)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.RGB);')
    append_constructor_hook('public PlatformImage(int Width, int Height)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.MUTABLE_SNAPSHOT, ImageObservation.SurfaceRole.OFFSCREEN);')
    append_constructor_hook('public PlatformImage(int Width, int Height, int ARGBcolor)',
                            'RuntimeAssets.created(this, ImageObservation.SourceKind.MUTABLE_SNAPSHOT, ImageObservation.SurfaceRole.OFFSCREEN);')
    # Existing derived-image constructors flow through Enhancement.derive, which
    # classifies them centrally and keeps them out of Phase 3 source capture.
    text = wrap_public_method(text, r'setPixel\(int x, int y, int color\)', 'this', suppress_raw=False)
    image.write_text(text,encoding='utf-8')
    graphics = SOURCE / 'mobile/PlatformGraphics.java'
    text = graphics.read_text(encoding='utf-8')
    text=text.replace('hdOriginal_flushGraphics(image, x, y, width, height); return;',
                      'hdOriginal_flushGraphics(image, x, y, width, height); Enhancement.frame(baseImage); return;')
    if 'hdOriginal_fillRect' not in text:
        text=text.replace('public void fillRect(int x, int y, int width, int height)',
                          'private void hdOriginal_fillRect(int x, int y, int width, int height)',1)
        wrapper='''
    public void fillRect(int x,int y,int width,int height) {
        if(Enhancement.SCALE==1 && !GpuRenderer.ENABLED) { hdOriginal_fillRect(x,y,width,height); return; }
        boolean outer=hdSuppress++==0;
        try { hdOriginal_fillRect(x,y,width,height); } finally { hdSuppress--; }
        if(outer) Enhancement.fill(this,x,y,width,height);
    }
'''
        text=text[:text.rfind('}')]+wrapper+'\n}\n'
    if 'hdWrite(' not in text:
        # All software pixel assignments retain their original evaluation order.
        pattern = r'canvasData\[([^\n;]+?)\]\s*=\s*([^;]+);'
        text, count = re.subn(pattern, lambda m: f'hdWrite({m[1]}, {m[2]});', text)
        assert count >= 20, f'Unexpected upstream raster implementation ({count} writes)'
        text = text.replace('protected boolean fastBlit;', '''protected boolean fastBlit;
    private int hdSuppress = 0;
    private void hdWrite(int index, int value) {
        canvasData[index] = value;
        if (hdSuppress == 0) Enhancement.pixel(baseImage, index, value);
    }
    private void hdCopy(int[] source, int offset, int[] destination, int target, int count) {
        System.arraycopy(source, offset, destination, target, count);
        if (hdSuppress == 0) for (int i=0; i<count; i++) Enhancement.pixel(baseImage, target+i, destination[target+i]);
    }
''')
        # The constructor initializes presentation storage before the first write.
        text = text.replace('canvas = image.getCanvas();', 'canvas = image.getCanvas();\n        Enhancement.surface(image);', 1)
        text = re.sub(r'System\.arraycopy\(([^;]+?), canvasData, ([^;]+?)\);', r'hdCopy(\1, canvasData, \2);', text)
        text = text.replace('gc.drawString(str, x, y);', 'gc.drawString(str, x, y);\n            Enhancement.text(this, str, x, y);')

        # Wrappers suppress low-resolution mirror writes while original image drawing runs.
        wrappers = []
        def wrap(signature, call):
            nonlocal text
            match = re.search(r'public void '+signature+r'\s*\{', text)
            assert match, signature
            declaration = match[0][:-1].strip()
            name = re.search(r'public void (\w+)', declaration)[1]
            params = declaration[declaration.index('(')+1:declaration.rindex(')')]
            args = ', '.join(part.strip().split()[-1] for part in params.split(','))
            original = declaration.replace('public void '+name, 'private void hdOriginal_'+name)
            text = text[:match.start()] + text[match.start():].replace(declaration, original, 1)
            wrappers.append(declaration + ''' {
        if (Enhancement.SCALE == 1 && !GpuRenderer.ENABLED) { hdOriginal_'''+name+'('+args+'''); return; }
        boolean outer = hdSuppress++ == 0;
        try { hdOriginal_'''+name+'('+args+'''); }
        finally { hdSuppress--; }
        if (outer) { '''+call+''' }
    }
''')
        wrap(r'drawImage\(Image image, int x, int y, int anchor\)',
             'Enhancement.blit(this, image, 0, 0, image.getWidth(), image.getHeight(), AnchorX(x,image.getWidth(),anchor), AnchorY(y,image.getHeight(),anchor), image.getWidth(), image.getHeight(), 0, false);')
        wrap(r'drawRegion\(Image image, int subx, int suby, int subw, int subh, int transform, int x, int y, int anchor\)',
             '''boolean rotate = transform >= 4;
             int dw = rotate ? subh : subw, dh = rotate ? subw : subh;
             if (Mobile.compatSiemensFriendlyDrawing) { if (translateX < 0) x -= translateX; if (translateY < 0) y -= translateY; }
             Enhancement.blit(this, image, subx, suby, subw, subh, AnchorX(x,dw,anchor), AnchorY(y,dh,anchor), dw, dh, transform, false);''')
        # The core transformed path uses DoJa's enum; convert back to MIDP for the presentation transform.
        wrap(r'drawTransformedImage\(PlatformImage image, int dx, int dy, int width, int height, int sx, int sy, int swidth, int sheight, int transform\)',
             'int[] transforms = {0,2,1,3,6,5,7,4}; Enhancement.blit(this,image,sx,sy,swidth,sheight,dx,dy,width,height,transforms[transform],false);')
        wrap(r'flushGraphics\(PlatformImage image, int x, int y, int width, int height\)',
             '''if (Mobile.maskIndex == 0 && !Mobile.funLightsEnabled) Enhancement.blit(this,image,x,y,width,height,x,y,width,height,0,true);
             else Enhancement.sync(baseImage,x,y,width,height);
             Enhancement.frame(baseImage);''')
        # Persistently drawn geometry uses instrumented low-resolution pixel writes.
        # copyArea must preserve detail, not copy its already reduced logical pixels.
        wrap(r'copyArea\(int x_src, int y_src, int width, int height, int x_dest, int y_dest, int anchor\)',
             '''Enhancement.blit(this,baseImage,x_src+translateX,y_src+translateY,width,height,AnchorX(x_dest,width,anchor),AnchorY(y_dest,height,anchor),width,height,0,true);''')
        text = text[:text.rfind('}')] + '\n' + '\n'.join(wrappers) + '\n}\n'
        graphics.write_text(text, encoding='utf-8')
    graphics.write_text(text, encoding='utf-8')
    text = graphics.read_text(encoding='utf-8')
    if 'hdRawRgbSuppression' not in text:
        text = text.replace('private int hdSuppress = 0;',
                            'private int hdSuppress = 0;\n    private int hdRawRgbSuppression = 0;')
    mutation_apis = [
        r'drawImage\(Image image, int x, int y, int anchor\)',
        r'drawRegion\(Image image, int subx, int suby, int subw, int subh, int transform, int x, int y, int anchor\)',
        r'drawTransformedImage\(PlatformImage image, int dx, int dy, int width, int height, int sx, int sy, int swidth, int sheight, int transform\)',
        r'flushGraphics\(PlatformImage image, int x, int y, int width, int height\)',
        r'copyArea\(int x_src, int y_src, int width, int height, int x_dest, int y_dest, int anchor\)',
        r'fillRect\(int x, int y, int width, int height\)',
        r'clearRect\(int x, int y, int width, int height\)',
        r'drawChar\(char character, int x, int y, int anchor\)',
        r'drawChars\(char\[\] data, int offset, int length, int x, int y, int anchor\)',
        r'drawChars\(char\[\] data, int x, int y, int offset, int length\)',
        r'drawImage\(Image image, int x, int y\)',
        r'drawRegion\(Image image, int subx, int suby, int subw, int subh, int transform, int x, int y, int width_dest, int height_dest, int anchor, int stretch_quality\)',
        r'drawLine\(int x1, int y1, int x2, int y2\)',
        r'drawArc\(int x, int y, int width, int height, int startAngle, int arcAngle\)',
        r'drawRect\(int x, int y, int width, int height\)',
        r'drawRoundRect\(int x, int y, int width, int height, int arcWidth, int arcHeight\)',
        r'drawString\(String str, int x, int y, int anchor\)',
        r'drawSubstring\(String str, int offset, int len, int x, int y, int anchor\)',
        r'fillArc\(int x, int y, int width, int height, int startAngle, int arcAngle\)',
        r'fillRoundRect\(int x, int y, int width, int height, int arcWidth, int arcHeight\)',
        r'drawImage\(javax\.microedition\.lcdui\.Image img, int x, int y, int anchor, int manipulation\)',
        r'drawPixels\(byte\[\] pixels, byte\[\] transparencyMask, int offset, int scanlength, int x, int y, int width, int height, int manipulation, int format\)',
        r'drawPixels\(int\[\] pixels, boolean transparency, int offset, int scanlength, int x, int y, int width, int height, int manipulation, int format\)',
        r'drawPixels\(short\[\] pixels, boolean transparency, int offset, int scanlength, int x, int y, int width, int height, int manipulation, int format\)',
        r'drawPolygon\(int\[\] xPoints, int xOffset, int\[\] yPoints, int yOffset, int nPoints, int argbColor\)',
        r'drawTriangle\(int x1, int y1, int x2, int y2, int x3, int y3\)',
        r'drawTriangle\(int x1, int y1, int x2, int y2, int x3, int y3, int argbColor\)',
        r'fillPolygon\(int\[\] xPoints, int xOffset, int\[\] yPoints, int yOffset, int nPoints, int argbColor\)',
        r'fillTriangle\(int x1, int y1, int x2, int y2, int x3, int y3\)',
        r'fillTriangle\(int x1, int y1, int x2, int y2, int x3, int y3, int argbColor\)',
        r'drawImage\(com\.nttdocomo\.ui\.Image image, int\[\] matrix\)',
        r'drawImage\(com\.nttdocomo\.ui\.Image image, int\[\] matrix, int sx, int sy, int width, int height\)',
        r'drawImage\(com\.nttdocomo\.ui\.Image image, int x, int y\)',
        r'drawImage\(com\.nttdocomo\.ui\.Image image, int dx, int dy, int sx, int sy, int width, int height\)',
        r'drawPolyline\(int\[\] xPoints, int\[\] yPoints, int nPoints\)',
        r'drawPolyline\(int\[\] xPoints, int\[\] yPoints, int offset, int count\)',
        r'fillPolygon\(final int\[\] xPoints, final int\[\] yPoints, final int numPoints\)',
        r'fillPolygon\(final int\[\] xPoints, final int\[\] yPoints, final int offset, final int numPoints\)',
        r'drawPolygon\(final int\[\] xPoints, final int\[\] yPoints, final int numPoints\)',
        r'drawPolygon\(final int\[\] xPoints, final int\[\] yPoints, final int offset, final int numPoints\)',
        r'drawScaledImage\(com\.nttdocomo\.ui\.Image image, int dx, int dy, int width, int height, int sx, int sy, int swidth, int sheight\)',
        r'drawSpriteSet\(com\.nttdocomo\.ui\.SpriteSet sprites\)',
        r'drawImageMap\(com\.nttdocomo\.ui\.ImageMap map, int x, int y\)',
        r'setPixel\(int x, int y\)',
        r'setPixel\(int x, int y, int color\)',
        r'setRGBPixel\(int x, int y, int color\)',
        r'setPixels\(int x, int y, int width, int height, int\[\] array, int offset\)',
        r'setRGBPixels\(int x, int y, int width, int height, int\[\] array, int offset\)',
        r'drawFunLights\(int\[\] pixelData, int width, int height\)',
        r'unlock\(boolean forced\)',
        r'flush\(\)',
        r'drawCommandList\(Texture texture, int x, int y, FigureLayout layout, Effect3D effect, int\[\] commandlist\)',
        r'drawCommandList\(Texture\[\] textures, int x, int y, FigureLayout layout, Effect3D effect, int\[\] commandlist\)',
        r'drawFigure\(Figure figure, int x, int y, FigureLayout layout, Effect3D effect\)',
        r'renderFigure\(Figure figure, int x, int y, FigureLayout layout, Effect3D effect\)',
        r'renderPrimitives\(Texture texture, int x, int y, FigureLayout layout, Effect3D effect, int command, int numPrimitives, int\[\] vertexCoords, int\[\] normals, int\[\] textureCoords, int\[\] colors\)',
        r'drawFigure\(com\.nttdocomo\.opt\.ui\.j3d\.Figure figure\)',
        r'executeCommandList\(int\[\] commandlist\)',
        r'renderFigure\(com\.nttdocomo\.opt\.ui\.j3d\.Figure figure\)',
        r'renderPrimitives\(com\.nttdocomo\.opt\.ui\.j3d\.PrimitiveArray primitives, int command\)',
        r'renderPrimitives\(com\.nttdocomo\.opt\.ui\.j3d\.PrimitiveArray primitives, int offset, int length, int command\)',
    ]
    for signature in mutation_apis:
        text = wrap_public_method(text, signature, 'baseImage')
    text = wrap_public_method(text,
        r'drawRGB\(int\[\] rgbData, int offset, int scanlength, int x, int y, int width, int height, boolean processAlpha\)',
        'baseImage', suppress_raw=False,
        post='if (hdRawRgbSuppression == 0) RuntimeAssets.rawRgbUsed(rgbData, offset, scanlength, width, height, processAlpha);')
    # Upgrade this wrapper on fresh and previously patched checkouts. Logical
    # drawing stays authoritative; suppress only its duplicate GPU pixel writes.
    rgb_wrapper = re.search(r'public void drawRGB\(int\[\] rgbData, int offset, int scanlength, int x, int y, int width, int height, boolean processAlpha\)\s*\{', text)
    if rgb_wrapper is None:
        raise RuntimeError('Shared drawRGB wrapper was not found')
    opening = text.index('{', rgb_wrapper.start())
    end, depth = opening + 1, 1
    while depth:
        if text[end] == '{': depth += 1
        elif text[end] == '}': depth -= 1
        end += 1
    text = text[:opening] + '''{
        // Runtime mutation boundary; RGB presentation uses an immutable source snapshot.
        RuntimeAssets.beginMutation(baseImage);
        try {
            RawRgbPresentation.Draw hdRgb = hdSuppress == 0 && hdRawRgbSuppression == 0
                    ? RawRgbPresentation.prepare(this, rgbData, offset, scanlength, x, y, width, height, processAlpha)
                    : null;
            if (hdRgb != null) hdSuppress++;
            try {
                hdMutationOriginal_drawRGB(rgbData, offset, scanlength, x, y, width, height, processAlpha);
            } finally { if (hdRgb != null) hdSuppress--; }
            if (hdRgb != null) hdRgb.render(this);
            else if (hdRawRgbSuppression == 0)
                RuntimeAssets.rawRgbUsed(rgbData, offset, scanlength, width, height, processAlpha);
        } finally { RuntimeAssets.endMutation(baseImage); }
    }''' + text[end:]
    graphics.write_text(text, encoding='utf-8')
    # Incremental upgrades are kept idempotent for already-patched checkouts.
    text = graphics.read_text(encoding='utf-8')
    if 'Enhancement.frame(baseImage)' not in text:
        text = text.replace('else Enhancement.sync(baseImage,x,y,width,height);', 'else Enhancement.sync(baseImage,x,y,width,height); Enhancement.frame(baseImage);')
    # 3D paths preserve original output until a dedicated 3D presentation path exists.
    if '// HD 3D fallback' not in text:
        text = re.sub(r'(mcv3gc\.(?:drawCommandList|drawFigure|renderFigure|renderPrimitives|flush)\([^;]*\);)',
                      r'\1 Enhancement.sync(baseImage,0,0,canvasWidth,canvasHeight); // HD 3D fallback', text)
    graphics.write_text(text, encoding='utf-8')
    frontend = SOURCE / 'freej2me/FreeJ2ME.java'
    text = frontend.read_text(encoding='utf-8')
    text = text.replace('Mobile.getPlatform().getLcdFrontbuffer().getCanvas()', 'org.recompile.mobile.Enhancement.surface(Mobile.getPlatform().getLcdFrontbuffer())')
    frontend.write_text(text, encoding='utf-8')
    for addition in (ROOT/'emulator-src').glob('*.java'):
        shutil.copy2(addition,SOURCE/'mobile'/addition.name)
    for obsolete in ('DecodedAssetCapture.java', 'PackedAssetProbe.java', 'MibSpriteDecoder.java'):
        stale = SOURCE / 'mobile' / obsolete
        if stale.exists(): stale.unlink()
    loader=SOURCE/'mobile/MIDletLoader.java'
    text=re.sub(r'(?m)^[ \t]*DecodedAssetCapture\.resource\([^;]*;[ \t]*\r?\n', '',
                loader.read_text(encoding='utf-8'))
    loader.write_text(text,encoding='utf-8')
    platform=SOURCE/'mobile/MobilePlatform.java'
    text=platform.read_text(encoding='utf-8')
    if '// Explicit emulator-owned screen role' not in text:
        text=text.replace('lcdFrontbuffer = new PlatformImage(width, height);',
            'lcdFrontbuffer = new PlatformImage(width, height);\n        RuntimeAssets.markScreen(lcdFrontbuffer); // Explicit emulator-owned screen role')
        text=text.replace('lcd = new PlatformImage(width, height);',
            'lcd = new PlatformImage(width, height);\n        RuntimeAssets.markScreen(lcd);')
        platform.write_text(text,encoding='utf-8')
    text=platform.read_text(encoding='utf-8')
    if '// Input queue telemetry' not in text:
        begin=text.index('public static void keyPressed(final int keycode)')
        end=text.index('public static void keyReleased',begin)
        block=text[begin:end]
        block=block.replace('Mobile.getDisplay().postInputEvent(new Runnable()',
                            'final long queuedAt=System.nanoTime(); // Input queue telemetry\n                Mobile.getDisplay().postInputEvent(new Runnable()',1)
        block=block.replace('if(!handleCommands(', 'Performance.input(queuedAt);\n                        if(!handleCommands(',1)
        text=text[:begin]+block+text[end:]
        platform.write_text(text,encoding='utf-8')
    text=platform.read_text(encoding='utf-8')
    if '// Bound keyboard target' not in text:
        for name,next_name in [('keyPressed','keyReleased'),('keyReleased','keyRepeated'),('keyRepeated','pointerDragged')]:
            begin=text.index('public static void '+name+'(');end=text.index('public static void '+next_name+'(',begin)
            block=text[begin:end]
            opening=block.index('{')+1
            block=block[:opening]+'\n        // Bound keyboard target: later UI events cannot retarget a queued key.\n        final Displayable keyTarget=Mobile.getDisplay()==null?null:Mobile.getDisplay().getCurrent();\n'+block[opening:]
            block=block.replace('(displayable = Mobile.getDisplay().getCurrent()) != null','keyTarget != null')
            block=re.sub(r'\bdisplayable\b','keyTarget',block)
            block=block.replace('handleCommands(Mobile.getCanvasAction(keycode))','handleCommands(keyTarget,Mobile.getCanvasAction(keycode))')
            text=text[:begin]+block+text[end:]
        begin=text.index('private static boolean handleCommands(int key)');end=text.index('public boolean load(',begin)
        block=text[begin:end].replace('handleCommands(int key)','handleCommands(Displayable keyTarget,int key)')
        block=re.sub(r'\bdisplayable\b','keyTarget',block)
        text=text[:begin]+block+text[end:];platform.write_text(text,encoding='utf-8')
    timing=SOURCE/'mobile/MIDletEnhancements.java'
    text=timing.read_text(encoding='utf-8')
    if '// Preserve game yield calibration on the GPU path.' not in text:
        text=text.replace('Mobile.getPlatform().limitFps();',
            '// Preserve game yield calibration on the GPU path.\n        if(Boolean.getBoolean("jme.gpu")) {Thread.yield();return;}\n        Mobile.getPlatform().limitFps();')
        timing.write_text(text,encoding='utf-8')
    mobile=SOURCE/'mobile/Mobile.java'
    text=mobile.read_text(encoding='utf-8')
    text=text.replace('String repaintOnSetCur = config.settings.get("compatrepaintonsetcurrent");',
        'String repaintOnSetCur = System.getProperty("jme.compat.repaintOnShow",config.settings.get("compatrepaintonsetcurrent"));')
    mobile.write_text(text,encoding='utf-8')
    # MIDP 2.0's LAYOUT_2 flag is valid (MrBeanRacer's wrapper uses 0x4001).
    item = SOURCE.parents[1] / 'javax/microedition/lcdui/Item.java'
    text = item.read_text(encoding='utf-8')
    text = text.replace('LAYOUT_NEWLINE_BEFORE | LAYOUT_NEWLINE_AFTER;',
                        'LAYOUT_NEWLINE_BEFORE | LAYOUT_NEWLINE_AFTER | LAYOUT_2;')
    item.write_text(text, encoding='utf-8')
    display = SOURCE.parents[1] / 'javax/microedition/lcdui/Display.java'
    text = display.read_text(encoding='utf-8')
    if 'runEventSafely' not in text:
        for name in ['inputTask', 'pendingPaint', 'pendingSerial', 'call']:
            text = text.replace(name + '.run();', 'runEventSafely(' + name + ');')
        helper = '''
    private static void runEventSafely(Runnable task) {
        try { task.run(); }
        catch (RuntimeException error) {
            Mobile.log(Mobile.LOG_ERROR, "MIDlet event failed; event processing will continue: " + error);
            error.printStackTrace();
        }
    }
'''
        text = text[:text.rfind('}')] + helper + '\n}\n'
    display.write_text(text, encoding='utf-8')
    canvas=SOURCE.parents[1]/'javax/microedition/lcdui/Canvas.java'
    text=canvas.read_text(encoding='utf-8')
    if 'paintInProgress' not in text:
        text=text.replace('protected volatile boolean needsRepaint = false;',
                          'protected volatile boolean needsRepaint = false;\n    protected volatile boolean paintInProgress = false;\n    protected volatile Thread paintThread;')
        begin=text.index('\tpublic void repaintRequest()')
        end=text.index('\tpublic void setFullScreenMode',begin)
        replacement='''
    public void repaintRequest() {
        if(!isShown() || listCommands) return;
        int renderX,renderY,renderW,renderH;
        synchronized(paintLock) {
            if(!needsRepaint || paintInProgress) {paintLock.notifyAll();return;}
            renderX=paintX;renderY=paintY;renderW=paintW;renderH=paintH;
            needsRepaint=false;
            paintInProgress=true;paintThread=Thread.currentThread();
        }
        try {
            try {
                graphics.reset(renderX,renderY,renderW,renderH);
                paint(graphics);
            } catch(Exception error) {
                Mobile.log(Mobile.LOG_ERROR,"Exception in Canvas paint: "+error);error.printStackTrace();
            }
            Mobile.getPlatform().setPostFlushDraw(postFlushDraw);
            if(hasFlushedToScreen) {hasFlushedToScreen=false;return;}
            Mobile.getPlatform().flushGraphics(platformImage,renderX,renderY,renderW,renderH);
            hasFlushedToScreen=false;
        } finally {
            synchronized(paintLock) {
                paintThread=null;paintInProgress=false;paintLock.notifyAll();
            }
        }
    }

    public void serviceRepaints() {
        while(Mobile.isPaused) {
            try {Thread.sleep(50);} catch(InterruptedException error){Thread.currentThread().interrupt();return;}
        }
        if(!isShown() || listCommands || Thread.currentThread()==paintThread)return;
        if(Mobile.getDisplay().isEventThread()) {repaintRequest();return;}
        for(;;) {
            boolean rescue;
            synchronized(paintLock) {
                if(!isShown() || (!needsRepaint&&!paintInProgress))return;
                try {paintLock.wait(1000);} catch(InterruptedException error){Thread.currentThread().interrupt();return;}
                rescue=needsRepaint&&!paintInProgress;
            }
            if(rescue&&isShown())repaintRequest();
        }
    }

'''
        text=text[:begin]+replacement+text[end:]
        canvas.write_text(text,encoding='utf-8')


def patch_m3g():
    """Keep raw software 3D writes inside one nested-safe presentation boundary."""
    path=ROOT/'vendor/freej2me-plus/src/javax/microedition/m3g/Graphics3D.java'
    text=path.read_text(encoding='utf-8')
    signatures=[r'clear\(Background background\)',r'render\(World world\)',
                r'render\(Node node, Transform transform\)',
                r'render\(VertexBuffer vertices, IndexBuffer triangles, Appearance appearance, Transform transform\)',
                r'render\(VertexBuffer vertices, IndexBuffer triangles, Appearance appearance, Transform transform, int scope\)']
    for signature in signatures:
        match=re.search(r'public void '+signature+r'\s*\{',text)
        if match is None:raise RuntimeError('M3G entry point changed: '+signature)
        opening=text.index('{',match.start())
        if '// M3G presentation boundary' in text[opening:opening+100]:continue
        end=opening+1;depth=1
        while depth:
            if text[end]=='{':depth+=1
            elif text[end]=='}':depth-=1
            end+=1
        declaration=text[match.start():opening].strip()
        name=re.search(r'void (\w+)',declaration).group(1)
        params=declaration[declaration.index('(')+1:declaration.rindex(')')]
        args=', '.join(part.strip().split()[-1] for part in params.split(','))
        original=text[match.start():end].replace('public void '+name,'private void m3gOriginal_'+name,1)
        wrapper=declaration+''' {
        // M3G presentation boundary; nested render calls publish once.
        try (org.recompile.mobile.M3gPresentation.Pass pass = org.recompile.mobile.M3gPresentation.begin(
                target, originX + viewx + viewClipL, originY + viewy + viewClipT,
                viewClipR - viewClipL, viewClipB - viewClipT)) {
            m3gOriginal_'''+name+'('+args+''');
        }
    }
'''
        text=text[:match.start()]+original+text[end:]
        text=text[:text.rfind('}')]+wrapper+text[text.rfind('}'):]
    path.write_text(text,encoding='utf-8')


if __name__ == '__main__':
    patch()
