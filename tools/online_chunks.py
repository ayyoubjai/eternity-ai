"""Phrase-level generation using Qwen's complete-waveform API."""
import re


def split_phrases(text, max_words=16):
    if max_words < 0:
        raise ValueError('max_words must be nonnegative')
    text = text.strip()
    if not text:
        return []
    if max_words == 0:
        return [text]
    phrases = []
    current = []
    for word in text.split():
        current.append(word)
        if len(current) >= max_words or re.search(r'[.!?;:][\"\u201d\u2019\')\]]*$', word):
            phrases.append(' '.join(current))
            current = []
    if current:
        phrases.append(' '.join(current))
    return phrases


def stream_phrases(qwen, ditto, text, request_id, max_words=16, report=print):
    phrases = split_phrases(text, max_words)
    for index, phrase in enumerate(phrases):
        chunk_id = f'{request_id}:{index + 1}'
        report(f'Generating phrase {index + 1}/{len(phrases)}...')
        qwen.send({'cmd': 'speak', 'id': chunk_id, 'text': phrase})
        audio = qwen.wait_for('audio', request_id=chunk_id)
        ditto.send({
            'cmd': 'play', 'id': chunk_id, 'path': audio['path'],
            'gap_ms': 350 if index == len(phrases) - 1 else 80,
        })
        ditto.wait_for('accepted', request_id=chunk_id)
        report(f"  Queued {audio['duration']:.2f}s of speech; generating the next phrase while Ditto runs.")
