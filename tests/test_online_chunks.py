from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from online_chunks import split_phrases, stream_phrases


class OnlineChunksTest(unittest.TestCase):
    def test_split_preserves_words_and_bounds(self):
        text = 'Hello there! This is a longer sentence without an early pause.'
        chunks = split_phrases(text, 4)
        self.assertEqual(' '.join(chunks), text)
        self.assertTrue(all(len(chunk.split()) <= 4 for chunk in chunks))
        self.assertEqual(chunks[0], 'Hello there!')
        self.assertEqual(split_phrases(text, 0), [text])
        self.assertEqual(split_phrases('   '), [])

    def test_first_phrase_reaches_ditto_before_next_generation(self):
        events = []
        class Service:
            def __init__(self, name): self.name = name
            def send(self, msg): events.append((self.name, msg))
            def wait_for(self, kind, request_id):
                events.append((self.name, kind, request_id))
                return dict(path=f'{request_id}.wav', duration=1)
        stream_phrases(Service('qwen'), Service('ditto'), 'First phrase. Second phrase.', 1, report=lambda _: None)
        self.assertEqual([e[0] for e in events], ['qwen', 'qwen', 'ditto', 'ditto'] * 2)
        self.assertEqual(events[2][1]['gap_ms'], 80)
        self.assertEqual(events[6][1]['gap_ms'], 350)
        self.assertNotEqual(events[0][1]['id'], events[4][1]['id'])

    def test_generation_error_stops_remaining_chunks(self):
        class Broken:
            def send(self, msg): pass
            def wait_for(self, *args, **kwargs): raise RuntimeError('generation failed')
        with self.assertRaises(RuntimeError):
            stream_phrases(Broken(), None, 'First. Second.', 1, report=lambda _: None)
