import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clone_profiles import clone_name, create_profile, load_profile


class ProfilesTest(unittest.TestCase):
    def test_imports_are_independent_and_portable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image, voice, transcript = [root / name for name in ('face.png', 'voice.wav', 'text.txt')]
            image.write_bytes(b'image')
            voice.write_bytes(b'audio')
            transcript.write_text('Hello world')
            for name in ('one', 'two'):
                create_profile(root, name, str(image), str(voice), str(transcript))
            image.unlink()
            voice.unlink()
            transcript.unlink()
            for name in ('one', 'two'):
                paths = load_profile(root, name)
                self.assertEqual(Path(paths['avatar']).read_bytes(), b'image')
                self.assertEqual(Path(paths['reference']).read_bytes(), b'audio')
                self.assertEqual(Path(paths['reference_text_file']).read_text(), 'Hello world\n')
                self.assertFalse(Path(paths['avatar']).is_symlink())
            with self.assertRaises(ValueError):
                create_profile(root, 'one')

    def test_invalid_names(self):
        for name in ('../escape', '/tmp/escape', '.', '', 'two words'):
            with self.assertRaises(ValueError):
                clone_name(name)

    def test_cancellation_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('builtins.input', side_effect=EOFError):
                with self.assertRaises(EOFError):
                    create_profile(root, 'cancelled')
            self.assertEqual(list((root / 'inputs').iterdir()), [])

    def test_capture_and_typed_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fake_capture(path, video=False):
                path.write_bytes(b'photo' if video else b'voice')
            with patch('clone_profiles.capture', side_effect=fake_capture), patch(
                'builtins.input', side_effect=['This is my voice.', '']
            ):
                create_profile(root, 'captured', 'camera', 'record', 'write')
            paths = load_profile(root, 'captured')
            self.assertEqual(Path(paths['reference_text_file']).read_text(), 'This is my voice.\n')

    def test_profile_cannot_reference_external_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / 'inputs' / 'unsafe'
            profile.mkdir(parents=True)
            (root / 'outside.png').write_bytes(b'image')
            (profile / 'clone.json').write_text(json.dumps({'avatar': '../../outside.png'}))
            with self.assertRaises(ValueError):
                load_profile(root, 'unsafe')


if __name__ == '__main__':
    unittest.main()
