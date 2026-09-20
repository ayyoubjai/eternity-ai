#!/usr/bin/env python3
"""Create portable, project-local clone profiles (no model dependencies)."""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clone_name(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value):
        raise ValueError('Use 1–64 lowercase letters, digits, hyphens or underscores; start with a letter or digit.')
    return value


def load_profile(root, name):
    directory = root / 'inputs' / clone_name(name)
    profile = json.loads((directory / 'clone.json').read_text(encoding='utf-8'))
    paths = {}
    for key in ('avatar', 'reference', 'reference_text_file'):
        path = (directory / profile[key]).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError(f'Invalid or missing {key} in clone {name}')
        paths[key] = str(path)
    return paths


def source_file(value):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'File does not exist: {path}')
    return path


def capture(destination, video=False):
    if not shutil.which('ffmpeg'):
        raise ValueError('Capture requires FFmpeg installed on the host. Alternatively supply a file path.')
    if video:
        device = input('Camera device [/dev/video0]: ').strip() or '/dev/video0'
        command = ['-f', 'v4l2', '-i', device, '-frames:v', '1']
        print('Taking a photo now...')
    else:
        device = input('PulseAudio/PipeWire source [default]: ').strip() or 'default'
        seconds = float(input('Recording duration in seconds [10]: ').strip() or '10')
        if not 0 < seconds <= 300:
            raise ValueError('Recording duration must be between 0 and 300 seconds.')
        input('Press Enter when ready to speak...')
        command = ['-f', 'pulse', '-i', device, '-t', str(seconds), '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le']
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *command, str(destination)], check=True)


def create_profile(root, name, image=None, voice=None, transcript=None):
    name = clone_name(name)
    inputs = root / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    destination = inputs / name
    if destination.exists():
        raise ValueError(f'Clone already exists: {name}. Choose another name.')
    # Stage the complete profile so cancelled prompts never leave a partial clone.
    with tempfile.TemporaryDirectory(prefix='.creating-', dir=inputs) as temporary:
        staging = Path(temporary)
        image = image or input('Portrait path (or "camera" to take a photo): ').strip()
        if image == 'camera':
            avatar = staging / 'avatar.png'
            capture(avatar, video=True)
        else:
            source = source_file(image)
            if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}:
                raise ValueError('Portrait must be PNG, JPEG, WebP, or BMP.')
            avatar = staging / ('avatar' + source.suffix.lower())
            shutil.copyfile(source, avatar)
        voice = voice or input('Voice WAV path (or "record" to use the microphone): ').strip()
        reference = staging / 'reference.wav'
        if voice == 'record':
            capture(reference)
        else:
            source = source_file(voice)
            if source.suffix.lower() != '.wav':
                raise ValueError('Voice reference must be a WAV file.')
            shutil.copyfile(source, reference)
        transcript = transcript or input('Exact voice transcript path (or "write" to enter it now): ').strip()
        if transcript == 'write':
            print('Enter exactly what was spoken in the voice reference. Press Enter on an empty line to finish (a single dot also works).')
            lines = []
            while True:
                line = input()
                if not line.strip() or line.strip() == '.':
                    break
                lines.append(line)
            text = '\n'.join(lines).strip()
        else:
            text = source_file(transcript).read_text(encoding='utf-8').strip()
        if not text:
            raise ValueError('The voice transcript cannot be empty.')
        (staging / 'reference.txt').write_text(text + '\n', encoding='utf-8')
        (staging / 'clone.json').write_text(json.dumps({
            'name': name, 'avatar': avatar.name,
            'reference': 'reference.wav', 'reference_text_file': 'reference.txt',
        }, indent=2) + '\n', encoding='utf-8')
        # mkdir reserves the name, including against concurrent creation.
        destination.mkdir()
        try:
            for path in staging.iterdir():
                shutil.move(str(path), destination / path.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='Interactively create a named clone on the host')
    create.add_argument('--name')
    create.add_argument('--image', help='Portrait path, or camera')
    create.add_argument('--voice', help='WAV path, or record')
    create.add_argument('--transcript', help='UTF-8 transcript path, or write')
    commands.add_parser('list', help='List locally configured clones')
    args = parser.parse_args()
    try:
        if args.command == 'list':
            for path in sorted((ROOT / 'inputs').glob('*/clone.json')):
                print(path.parent.name)
            return
        name = args.name or input('Clone name (e.g. personal or mr-house): ').strip()
        result = create_profile(ROOT, name, args.image, args.voice, args.transcript)
        print(f'Clone created: {result}')
        print(f'Run: ./scripts/run-docker.sh --clone {name} --mode live')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Cannot create clone: {exc}\n')
    except (EOFError, KeyboardInterrupt):
        parser.exit(130, '\nClone creation cancelled.\n')


if __name__ == '__main__':
    main()
