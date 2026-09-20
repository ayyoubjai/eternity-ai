"""Check that live streaming reuses the launcher's window."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


class LiveWindowTest(unittest.TestCase):
    def test_external_window_receives_stream_without_ffplay(self):
        source = Path(__file__).resolve().parents[1] / 'tools/ditto_live_service.py'
        tree = ast.parse(source.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LiveVideoWriter')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_open')
        os = MagicMock()
        os.pipe.side_effect = [(10, 11), (12, 13)]
        subprocess = MagicMock()
        socket = MagicMock()
        threading = MagicMock()
        namespace = dict(os=os, subprocess=subprocess, socket=socket,
                         threading=threading, Path=Path, json=json,
                         sys=SimpleNamespace(executable='python3'),
                         np=SimpleNamespace(asarray=lambda frame: frame))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        writer = SimpleNamespace(fps=25, mpv_socket='/tmp/test-mpv.sock',
                                 record_path=None, _audio_loop=lambda: None)
        namespace['_open'](writer, SimpleNamespace(shape=(64, 64, 3)))
        commands = [call.args[0] for call in subprocess.Popen.call_args_list]
        self.assertEqual(commands[0][0], 'ffmpeg')
        self.assertFalse(any(command[0] == 'ffplay' for command in commands))
        os.mkfifo.assert_called_once_with(Path('/tmp/test-mpv.sock.nut'), 0o600)
        client = socket.socket.return_value.__enter__.return_value
        messages = [json.loads(call.args[0])['command'] for call in client.sendall.call_args_list]
        self.assertIn(['loadfile', '/tmp/test-mpv.sock.nut', 'replace'], messages)
        self.assertIn(['set_property', 'pause', False], messages)
