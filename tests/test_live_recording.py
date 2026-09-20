"""Exercise the actual recording finalizer without importing GPU services."""
import ast
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class RecordingTest(unittest.TestCase):
    def test_multiple_voice_clips_are_muxed_into_video(self):
        source = Path(__file__).resolve().parents[1] / 'tools/ditto_live_service.py'
        tree = ast.parse(source.read_text())
        writer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LiveVideoWriter')
        finish = next(n for n in writer.body if isinstance(n, ast.FunctionDef) and n.name == '_finish_recording')
        module = ast.Module(body=[finish], type_ignores=[])
        namespace = dict(Path=Path, json=json, os=os, subprocess=subprocess, sys=sys)
        exec(compile(module, str(source), 'exec'), namespace)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            obj = type('Writer', (), {})()
            obj.record_path = root / 'demo.mp4'
            obj.record_tmp_path = root / 'video.mp4'
            obj.record_mux_path = root / 'mux.mp4'
            obj.record_frames = queue.Queue()
            obj.record_thread = None
            obj.record_error = None
            obj.fps = 25
            obj.audio_delay = 0
            obj.playback_end_frame = 50
            obj.record_proc = subprocess.Popen([
                'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'color=size=64x64:rate=25:duration=2', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', str(obj.record_tmp_path),
            ], stdin=subprocess.PIPE)
            obj.record_proc.wait(timeout=15)
            wav = root / 'voice.wav'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=0.5', str(wav),
            ], check=True)
            obj.record_events = [
                dict(path=str(wav), start_seconds=start, audio_delay_ms=0)
                for start in (0, 1)
            ]
            namespace['_finish_recording'](obj)
            info = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(obj.record_path),
            ]))
            streams = {s['codec_type']: s for s in info['streams']}
            self.assertEqual(set(streams), {'audio', 'video'})
            self.assertAlmostEqual(float(streams['video']['duration']), 2, places=1)
            self.assertAlmostEqual(float(streams['audio']['duration']), 1.5, places=1)
            self.assertFalse(obj.record_tmp_path.exists())
            self.assertTrue(Path(str(obj.record_path) + '.json').exists())


if __name__ == '__main__':
    unittest.main()
