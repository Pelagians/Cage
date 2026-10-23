"""Small application-specific GUI actions; package/state assertions stay shared."""
from pathlib import Path
import fcntl
import os
import re
import struct
import time
import xml.etree.ElementTree as ET


def share_test_windows(state, shared):
    """Optional Btrfs proof-space optimization; retain every independent file.

    Called only after successful normal shutdown. Never enabled by production
    or CI. Kernel equality checks keep differing Windows bytes unchanged.
    """
    source = os.environ.get('CAGE_TEST_SHARE_WINDOWS')
    if not source:
        return
    from runtime.desktop_launch import lifecycle_lock, _read_generations
    with lifecycle_lock(state):
        before = (state / 'state.json').read_bytes()
        for entry in _read_generations(state)['generations']:
            if entry['prefix'] in shared:
                continue
            windows = state / entry['prefix'] / 'drive_c/windows'
            for target in windows.rglob('*'):
                src = Path(source) / target.relative_to(windows)
                if target.is_symlink() or src.is_symlink() or not target.is_file() or not src.is_file():
                    continue
                size = target.stat().st_size
                if size < 1024**2 or size != src.stat().st_size:
                    continue
                with src.open('rb') as a, target.open('r+b') as b:
                    for offset in range(0, size, 16 * 1024**2):
                        length = min(16 * 1024**2, size - offset)
                        data = bytearray(struct.pack('=QQHHI', offset, length, 1, 0, 0)
                                         + struct.pack('=qQQiI', b.fileno(), offset, 0, 0, 0))
                        fcntl.ioctl(a.fileno(), 0xc0189436, data, True)
                        if struct.unpack_from('=i', data, 48)[0] not in (0, 1):
                            raise RuntimeError('extent verification refused')
            shared.add(entry['prefix'])
        assert before == (state / 'state.json').read_bytes()


class SumatraPDF:
    app_id = 'io.github.Pelagians.Cage.SumatraPDF'
    window_pattern = 'SumatraPDF'
    extension = '.pdf'
    executable = 'drive_c/Program Files/SumatraPDF/SumatraPDF.exe'

    def fixture(self, path):
        # A deterministic two-page PDF, with no external fonts or fixture data.
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
                   b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
        for page in (1, 2):
            content = f'BT /F1 24 Tf 48 700 Td (Cage PDF qualification page {page}) Tj ET\n'.encode()
            objects.append(b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'endstream')
        data = bytearray(b'%PDF-1.4\n'); offsets = [0]
        for number, body in enumerate(objects, 1):
            offsets.append(len(data)); data.extend(f'{number} 0 obj\n'.encode() + body + b'\nendobj\n')
        xref = len(data); data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
        for offset in offsets[1:]:data.extend(f'{offset:010d} 00000 n \n'.encode())
        data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
        path.write_bytes(data)

    def change_preference(self, gui):
        # Invoke the real command through its palette. Xvfb/Wine function-key
        # mappings vary; ordinary text input selects the same application action.
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+k')
        time.sleep(.5)
        gui.command('xdotool', 'type', '--clearmodifiers', '--delay', '50', '>toolbar')
        time.sleep(.5)
        gui.command('xdotool', 'key', '--clearmodifiers', 'Return')

    def preference(self, prefix):
        settings = prefix / 'drive_c/users/Public/AppData/Local/SumatraPDF/SumatraPDF-settings.txt'
        match = re.search(r'(?m)^\s*ShowToolbar\s*=\s*(true|false)\s*$', settings.read_text())
        return match[1] if match else None

    def save_keys(self, gui):
        gui.command('xdotool', 'key', '--clearmodifiers', 'ctrl+s')

    def validate_saved(self, path, expected):
        assert path.read_bytes() == expected and expected.startswith(b'%PDF-'), 'saved PDF bytes changed'


class NotepadPlusPlus:
    app_id = 'io.github.Pelagians.Cage.NotepadPlusPlus'
    window_pattern = 'Notepad\\+\\+'
    extension = '.txt'
    executable = 'drive_c/Program Files/Notepad++/notepad++.exe'

    def fixture(self, path):path.write_text('Cage shared onboarding workflow\n')

    def change_preference(self, gui):
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+v')
        gui.command('xdotool', 'key', '--delay', '80', 'Home', *(['Down'] * 6), 'Right', 'Home', 'Return')

    def preference(self, prefix):
        matches = list(prefix.glob('drive_c/users/*/AppData/Roaming/Notepad++/config.xml'))
        return ET.parse(matches[0]).find(".//GUIConfig[@name='ScintillaPrimaryView']").get('zoom')

    def save_keys(self, gui):
        gui.command('xdotool', 'key', '--clearmodifiers', 'alt+f')
        gui.command('xdotool', 'key', '--clearmodifiers', 'a')

    def validate_saved(self, path, expected):assert path.read_bytes() == expected


WORKFLOWS = {'sumatrapdf': SumatraPDF, 'notepadplusplus': NotepadPlusPlus}
