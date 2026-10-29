import io
import lzma
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image

from asset_decoding import decode_jar, embedded_pngs
from engine import image_id, runtime_arguments
from gameloft_resources import layout, unpack


class AssetDecodingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def png(self,color='red'):
        buffer=io.BytesIO();Image.new('RGBA',(7,9),color).save(buffer,format='PNG')
        return buffer.getvalue()

    def jar(self,entries):
        path=self.root/'game.jar'
        with zipfile.ZipFile(path,'w') as archive:
            for name,data in entries.items():archive.writestr(name,data)
        return path

    def decode(self,path,folder='out'):
        return decode_jar(path,self.root/folder,image_id,'unused-java',self.root/'missing-player.jar')

    def pack(self,blocks):
        header=6+4*(len(blocks)+1);offsets=[header]
        for block in blocks:offsets.append(offsets[-1]+len(block))
        return struct.pack('<HHH',len(blocks),1,0)+struct.pack('<'+'I'*len(offsets),*offsets)+b''.join(blocks)

    def test_ordinary_images_skip_custom_code_and_repeat_uses_cache(self):
        path=self.jar({'texture.png':self.png(),'main.class':b'not executed'})
        with patch('subprocess.run',side_effect=AssertionError('Image import must not execute code')):
            report,records=self.decode(path)
            stamp=(self.root/'out/original-assets'/(records[0]['image_id']+'.png')).stat().st_mtime_ns
            again,_=self.decode(path)
        self.assertFalse(report['additional_decoding'])
        self.assertEqual(report['unique_images'],1)
        self.assertEqual(report,again)
        self.assertEqual(stamp,(self.root/'out/original-assets'/(records[0]['image_id']+'.png')).stat().st_mtime_ns)

    def test_static_lzma_container_images_and_unknown_codec_are_distinguished(self):
        container=self.pack([bytes([129])+lzma.compress(self.png(),format=lzma.FORMAT_ALONE),
                             bytes([2])+b'\xdf\x05unknown-sprite-codec'])
        path=self.jar({'asset.pack':container})
        with patch('subprocess.run',side_effect=AssertionError('Unknown code must not execute')):
            report,records=self.decode(path)
        self.assertTrue(report['additional_decoding'])
        self.assertEqual(report['container_blocks'],2)
        self.assertEqual(report['unique_images'],1)
        self.assertNotIn('sprite_blocks_decoded',report)
        self.assertNotIn('decoded_rgb_lookup',report['features'])

    def test_truncated_tables_and_decompression_limit_are_rejected(self):
        payload=self.pack([bytes([129])+lzma.compress(b'A'*100,format=lzma.FORMAT_ALONE)])
        self.assertIsNone(layout('pack',{'pack':payload[:-1]}.__getitem__))
        parts=layout('pack',{'pack':payload}.__getitem__)
        with patch('gameloft_resources.MAX_BLOCK',20),self.assertRaises(ValueError):
            list(unpack(parts,{'pack':payload}.__getitem__))

    def test_embedded_png_crc_and_unsupported_format(self):
        png=self.png();corrupt=bytearray(png);corrupt[-1]^=1
        self.assertEqual(len(list(embedded_pngs(b'prefix'+png+b'suffix'))),1)
        self.assertEqual(list(embedded_pngs(corrupt)),[])
        report,_=self.decode(self.jar({'resource':b'unknown graphics data'}))
        self.assertEqual(report['decision'],'unknown')

    def test_runtime_observation_policy_is_shared_and_adds_no_control_workarounds(self):
        self.assertEqual(runtime_arguments('0'*64),[])
        game={'asset_decoding':{'features':{'decoded_rgb_lookup':True}}}
        self.assertEqual(runtime_arguments('0'*64,game),[])
        from asset_decoding import default_registry
        self.assertEqual([decoder.name for decoder in default_registry().decoders],
                         ['standard-images-v1','embedded-png-v1','gameloft-offset-lzma-v1'])

    def test_icon_does_not_hide_an_unknown_packed_or_generated_pixel_path(self):
        path=self.jar({'icon.png':self.png(),'sprite.dat':b'undocumented binary format',
                       'game.class':b'createRGBImage'})
        report,_=self.decode(path)
        self.assertEqual(report['decision'],'unresolved-pixel-path')
        self.assertIsNone(report['additional_decoding'])


if __name__=='__main__':unittest.main()
