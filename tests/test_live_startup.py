"""A short utterance must reach playback without closing the session pipes."""
import ast
import os
from pathlib import Path
import select
import shutil
import subprocess
import threading
import time
import unittest
from types import SimpleNamespace


@unittest.skipUnless(shutil.which('ffmpeg'), 'requires FFmpeg')
class LiveStartupTest(unittest.TestCase):
    def test_mux_emits_media_before_eof(self):
        source = Path(__file__).resolve().parents[1] / 'tools/ditto_live_service.py'
        tree = ast.parse(source.read_text())
        writer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LiveVideoWriter')
        method = next(n for n in writer.body if isinstance(n, ast.FunctionDef) and n.name == '_open')
        assignment = next(n for n in method.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'mux_cmd' for t in n.targets))
        vr, vw = os.pipe()
        ar, aw = os.pipe()
        env = dict(self=SimpleNamespace(width=64, height=64, fps=25), video_read=vr, audio_read=ar)
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(source), 'exec'), env)
        proc = subprocess.Popen(env['mux_cmd'], pass_fds=(vr, ar), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        player_assignment = next(n for n in method.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'player_cmd' for t in n.targets))
        exec(compile(ast.Module(body=[player_assignment], type_ignores=[]), str(source), 'exec'), env)
        options = env['player_cmd'][1:]
        for flag in ('-framedrop', '-autoexit'):
            options.remove(flag)
        index = options.index('-sync')
        del options[index:index + 2]
        decoder = subprocess.Popen(['ffmpeg', *options, '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], stdin=proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdout.close()
        os.close(vr)
        os.close(ar)
        def feed(fd, payload):
            try:
                with os.fdopen(fd, 'wb', buffering=0) as stream:
                    stream.write(payload)
                    release.wait(8)
            except BrokenPipeError:
                pass
        release = threading.Event()
        threads = [threading.Thread(target=feed, args=(vw, bytes(64 * 64 * 3 * 25))),
                   threading.Thread(target=feed, args=(aw, bytes(16000 * 4)))]
        for thread in threads:
            thread.start()
        try:
            received = 0
            deadline = time.monotonic() + 3
            while received < 64 * 64 * 3 and time.monotonic() < deadline:
                readable, _, _ = select.select([decoder.stdout], [], [], max(0, deadline - time.monotonic()))
                if readable:
                    data = os.read(decoder.stdout.fileno(), 65536)
                    if not data:
                        break
                    received += len(data)
            self.assertGreaterEqual(received, 64 * 64 * 3, 'Mux buffered media until EOF')
        finally:
            release.set()
            decoder.terminate()
            decoder.communicate(timeout=5)
            proc.terminate()
            proc.communicate(timeout=5)
            for thread in threads:
                thread.join(timeout=5)
