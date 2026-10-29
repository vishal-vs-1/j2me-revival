"""Read-only evidence about a JAR's drawing paths and extraction coverage."""
from pathlib import Path
import zipfile

VERSION=2
TERMS={'sprite_api':b'javax/microedition/lcdui/game/Sprite',
       'draw_region':b'drawRegion','raw_rgb_images':b'createRGBImage','raw_rgb_draws':b'drawRGB',
       'encoded_images':b'([BII)Ljavax/microedition/lcdui/Image;',
       'draw_image':b'drawImage','set_clip':b'setClip',
       'm3g':b'javax/microedition/m3g','mascot_3d':b'com/mascotcapsule',
       'system_font':b'javax/microedition/lcdui/Font',
       'derived_regions':b'(Ljavax/microedition/lcdui/Image;IIIII)Ljavax/microedition/lcdui/Image;'}

def handling_plan(hits,archive_images,packed,embedded,font_resources):
    """Select reportable handling paths, never equating a detected API with complete support."""
    paths=[]
    def add(kind,label,evidence,handler,support,next_step):
        paths.append({'kind':kind,'label':label,'evidence':evidence,'active_handler':handler,
                      'support':support,'next_step':next_step})
    if archive_images:
        add('source_images','Extractable source images',{'images':archive_images},'source_texture_pack',
            'supported_for_extracted_sources','Reuse saved HD textures while retaining original logical dimensions.')
    clipped_images=sorted(set(hits['draw_image'])&set(hits['set_clip']))
    if hits['draw_region'] or hits['sprite_api'] or clipped_images:
        add('region_sprites','Sprite sheets / image regions',{'classes':sorted(set(hits['draw_region']+hits['sprite_api']+clipped_images)),
            'clipped_image_candidates':clipped_images},
            'atlas_region_preservation','supported_for_tracked_sources',
            'Preserve source rectangles, anchors and flips; identify animation groupings before changing artwork.')
    if hits['derived_regions']:
        add('derived_regions','Derived image regions',{'classes':hits['derived_regions']},'inherit_parent_hd',
            'supported_for_tracked_sources','Reuse parent HD pixels instead of enhancing every copy.')
    if hits['raw_rgb_images'] or hits['raw_rgb_draws']:
        add('decoded_or_generated_pixels','Decoded / generated pixel images',
            {'classes':sorted(set(hits['raw_rgb_images']+hits['raw_rgb_draws']))},'logical_pixel_compatibility',
            'enlargement_only_when_source_is_untracked',
            'Trace decoding to stable source/module/palette identities; separate artwork from effects and resized copies.')
    if hits['encoded_images']:
        add('encoded_images','Byte-array image decoding',{'classes':hits['encoded_images']},'source_hash_lookup_with_unknown_fallback',
            'supported_only_when_source_identity_is_known',
            'Relate decoded bytes to archive sources or a known decoder; do not cache every runtime resize as source artwork.')
    limited=archive_images is not None and archive_images<=1 and bool(packed) and bool(hits['draw_region'] or hits['raw_rgb_images'])
    if limited:
        add('packed_graphics','Likely packed gameplay graphics',{'candidate_resources':len(packed)},
            'original_game_decoder','extractor_or_source_tracking_required',
            'Identify resource format and decoder version, then extract stable modules before runtime transformations.')
    if embedded:
        add('embedded_images','Embedded PNG candidates',{'signature_counts':embedded},'none',
            'inspection_only','Validate complete image boundaries and purpose; signatures alone do not identify animation frames.')
    if font_resources:
        add('bitmap_fonts','Named bitmap fonts',{'resources':font_resources},'smooth_text_pack',
            'supported_for_identified_resources','Preserve glyph rectangles and advances; avoid neural repainting of text.')
    if hits['system_font']:
        add('system_text','Standard Java text',{'classes':hits['system_font']},'hd_text_rasterization',
            'gpu_presentation_supported','Retain original logical metrics and readback.')
    has_3d=bool(hits['m3g'] or hits['mascot_3d'])
    if has_3d:
        add('three_d','3D APIs',{'classes':sorted(set(hits['m3g']+hits['mascot_3d']))},'original_3d_output',
            'compatibility_output_only','Use a separate 3D texture/rendering path; 2D replacement does not establish 3D enhancement.')
    if not paths:
        add('unknown','Unknown graphics path',{},'original_game_output','runtime_trace_required',
            'Observe actual decoding/drawing calls before choosing an enhancement handler.')
    if limited:primary='packed_2d_with_custom_decoding'
    elif has_3d:primary='3d_or_mixed_2d_3d'
    elif hits['raw_rgb_images'] or hits['raw_rgb_draws'] or hits['encoded_images']:primary='mixed_2d_sources_and_decoding'
    elif hits['draw_region'] or hits['sprite_api'] or clipped_images:primary='source_images_and_regions'
    elif archive_images:primary='source_images'
    else:primary='unknown'
    return {'primary_strategy':primary,'paths':paths,'evidence_level':'static archive/API references',
            'runtime_validated':False,'complete_hd_coverage':None,
            'logical_contract':'Original dimensions, source rectangles, anchors, collision pixels and game timing remain authoritative.',
            'jar_policy':'Keep original resources; attach HD assets and a mapping manifest for the custom player. Direct size-changing substitution needs code/metadata adaptation.',
            'next_runtime_checks':['Identify decoder inputs, output modules and palette variants.',
                                   'Record source relationships through crops, resizing and pixel effects.',
                                   'Measure enhanced versus fallback drawing in representative gameplay.',
                                   'Validate complete animation cycles, timing, transparency and collisions.']}

def inspect(path,archive_images=None):
    with zipfile.ZipFile(path) as jar:
        files=jar.infolist();classes=[file for file in files if file.filename.endswith('.class')]
        hits={key:[] for key in TERMS}
        for file in classes:
            data=jar.read(file)
            for key,needle in TERMS.items():
                if needle in data:hits[key].append(file.filename)
        resources=[file for file in files if not file.is_dir() and not file.filename.endswith('.class') and not file.filename.upper().startswith('META-INF/')]
        packed=[file for file in resources if Path(file.filename).suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.mid','.midi','.wav','.mp3','.amr','.txt'}]
        embedded={file.filename:jar.read(file).count(b'\x89PNG\r\n\x1a\n') for file in packed if file.file_size<=16*1024*1024}
        embedded={key:value for key,value in embedded.items() if value}
        fonts=[file.filename for file in resources if 'font' in Path(file.filename).name.lower()]
    plan=handling_plan(hits,archive_images,packed,embedded,fonts)
    custom=bool(hits['draw_region'] and not hits['sprite_api'])
    limited=archive_images is not None and archive_images<=1 and bool(packed) and bool(hits['draw_region'] or hits['raw_rgb_images'])
    return {'inspection_version':VERSION,'bytes':Path(path).stat().st_size,'entries':len(files),'classes':len(classes),
            'archive_images':archive_images,'packed_resources':len(packed),'embedded_png_signatures':embedded,
            'drawing_evidence':hits,'custom_sprite_engine_likely':custom,'packed_graphics_likely':limited,
            'handling_plan':plan,
            'animation_note':'Custom region/pixel drawing is present; frame timing and composition remain controlled by game code.' if custom else 'Animation remains controlled by game code; individual image files do not establish frame sequences.',
            'coverage_note':'Partial HD: packed graphics need an extractor or stable source tracking.' if limited else 'Extracted source images are prepared; complete animation/level coverage has not been measured.'}
