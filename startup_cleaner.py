"""Prepare reversible startup repairs, independently of rendering and input.

Only exact, reviewed archive versions may be transformed. Finding a promotional
string is evidence to inspect, never permission to delete an arbitrary class.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
MRBEAN = '061f71e5ad66befade2c6d2bbcca1e5a76c4cf9a7782f82cd80ab8a1e4cc56d6'
HANDLERS = {
    MRBEAN: {
        'recipe': 'mrbean-startup-v1',
        'source': ROOT / 'compatibility-src/mrbean/WRAPPER.java',
        'retained_classes': {'WRAPPER', 'a', 'o', 'p'},
        'providers': ['MobileRated', 'HOVR/Kalador'],
    },
}
VERSION = 1


def supports_cleanup(identity):
    return identity in HANDLERS


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def class_references(data):
    """Read class/descriptor references, excluding unrelated one-letter names."""
    if data[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError('Invalid class header')
    count = struct.unpack_from('>H', data, 8)[0]
    strings, classes = {}, []
    index, offset = 1, 10
    while index < count:
        tag = data[offset]
        offset += 1
        if tag == 1:
            length = struct.unpack_from('>H', data, offset)[0]
            offset += 2
            strings[index] = data[offset:offset + length].decode('utf-8', errors='replace')
            offset += length
        elif tag == 7:
            classes.append(struct.unpack_from('>H', data, offset)[0])
            offset += 2
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            offset += 4
        elif tag in (5, 6):
            offset += 8
            index += 1
        elif tag in (8, 16, 19, 20):
            offset += 2
        elif tag == 15:
            offset += 3
        else:
            raise ValueError(f'Unsupported class constant {tag}')
        index += 1
    refs = {strings[item] for item in classes}
    refs.update(name for text in strings.values() for name in re.findall(r'L([^;()]+);', text))
    return refs


def inspect_startup(source):
    """Unknown archives are reported and left intact, including signed archives."""
    identity = digest(source)
    handler = HANDLERS.get(identity)
    signals = set()
    with zipfile.ZipFile(source) as jar:
        for item in jar.infolist():
            if item.filename.endswith('.class') and item.file_size < 4 * 1024 * 1024:
                data = jar.read(item)
                if b'mobilerated.com' in data:
                    signals.add('MobileRated')
                if b'hovr.com' in data:
                    signals.add('HOVR')
    return {
        'inspection_version': VERSION, 'source_sha256': identity,
        'status': 'verified_wrapper' if handler else ('unrecognized_wrapper' if signals else 'unchanged'),
        'signals': sorted(signals), 'recipe': handler['recipe'] if handler else None,
        'note': ('Verified promotional/network startup wrappers; a reviewed repair is available.' if handler
                 else 'Promotional wrapper indicators found; no verified repair, archive retained.' if signals
                 else 'No verified startup repair applies; archive retained.'),
    }


def _write_report(path, report):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temp:
        json.dump(report, temp, indent=2)
    os.replace(temp.name, path)


def select_startup(source, output, *, enabled=False, javac=None, player=None, progress=lambda message: None):
    """Off by default: inspecting a wrapper never implicitly enables removal."""
    if enabled:
        return prepare_startup(source, output, javac=javac, player=player, progress=progress)
    return Path(source), inspect_startup(source)


def prepare_startup(source, output, *, javac=None, player=None, progress=lambda message: None):
    """Return playable path + evidence. Reuse a checked derivative on later runs."""
    source, output = Path(source), Path(output)
    report = inspect_startup(source)
    handler = HANDLERS.get(report['source_sha256'])
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / 'startup.json'
    if handler is None:
        try:
            previous = json.loads(report_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = None
        if previous != report:
            _write_report(report_file, report)
        return source, report

    adapter_source = handler['source']
    report['adapter_source_sha256'] = digest(adapter_source)
    playable = output / 'playable.jar'
    try:
        previous = json.loads(report_file.read_text(encoding='utf-8'))
        if (previous['recipe'] == report['recipe']
                and previous['source_sha256'] == report['source_sha256']
                and previous['adapter_source_sha256'] == report['adapter_source_sha256']
                and previous['status'] == 'cleaned'
                and digest(playable) == previous['playable_sha256']):
            return playable, previous
    except (OSError, ValueError, KeyError):
        pass

    if not javac or not player or not Path(player).is_file():
        raise RuntimeError('The startup repair needs the built player and a Java JDK.')
    progress('Step 1: removing verified MobileRated / HOVR startup wrappers…')
    with tempfile.TemporaryDirectory(prefix='startup-', dir=output) as work:
        work = Path(work)
        result = subprocess.run(
            [str(javac), '--release', '8', '-encoding', 'UTF-8', '-cp',
             str(source) + os.pathsep + str(player), '-d', str(work), str(adapter_source)],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Startup adapter compilation failed: ' + result.stderr[-2500:])
        replacement = (work / 'WRAPPER.class').read_bytes()
        temporary = work / 'playable.jar'
        with zipfile.ZipFile(source) as jar:
            names = {item.filename[:-6] for item in jar.infolist() if item.filename.endswith('.class')}
            retained = handler['retained_classes']
            if not retained <= names:
                raise ValueError('Verified startup classes are missing')
            # Check all game class/descriptor edges before removing wrapper classes.
            for name in retained:
                data = replacement if name == 'WRAPPER' else jar.read(name + '.class')
                missing = (class_references(data) & names) - retained
                if missing:
                    raise ValueError(f'Startup repair would remove dependencies of {name}: {missing}')
            removed = sorted((names - retained))
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
                for item in jar.infolist():
                    if item.filename.endswith('.class') and item.filename[:-6] in removed:
                        continue
                    # Preserve manifest, resources and actual gameplay bytecode verbatim.
                    target.writestr(item, replacement if item.filename == 'WRAPPER.class' else jar.read(item))
        report.update(status='cleaned', removed_classes=[name + '.class' for name in removed],
                      replaced_classes=['WRAPPER.class'], retained_game_classes=['a.class', 'o.class', 'p.class'],
                      playable_sha256=digest(temporary),
                      note='MobileRated and HOVR startup code removed. Starts the original game directly; original JAR preserved.')
        os.replace(temporary, playable)
    _write_report(report_file, report)
    progress('Startup prepared — original game starts directly; saved copy reused next time.')
    return playable, report
