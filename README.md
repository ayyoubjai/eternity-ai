# Digital Clone

An interactive talking-head clone built from two model families only:

- **Qwen3-TTS** clones a reference voice and generates a complete WAV file.
- **Ditto Talking Head** animates a source portrait from that WAV file.

Offline mode renders a complete synchronized MP4, applies a visual
style, and loads each response into one persistent MPV window. A lower-latency
online mode is included for experimentation.

## See it in action

These selected outputs show a still portrait animated to match synthesized speech
from a reference voice. Each clip includes video and audio. Open a video link to
view or download the MP4, and enable sound when playing it.

- **Ayyoub:** a personal talking-head example using the author's portrait and voice.
- **Mr. House:** an unofficial AI-generated *Fallout: New Vegas* fan demonstration,
  using the clone name `dr-house`.

| Clone | Finished video | Duration |
| --- | --- | --- |
| Ayyoub | [Watch personal clone demo](examples/ayyoub/ditto_offline_20260920_223658_00001.mp4) | 4.2 s |
| Mr. House | [Watch character demo 1](examples/dr-house/ditto_offline_20260905_070806_00002.mp4) | 2.9 s |
| Mr. House | [Watch character demo 2](examples/dr-house/ditto_offline_20260905_072719_00002.mp4) | 1.4 s |
| Mr. House | [Watch character demo 3](examples/dr-house/ditto_offline_20260905_073602_00002.mp4) | 1.6 s |
| Mr. House | [Watch character demo 4](examples/dr-house/ditto_offline_20260905_081237_00003.mp4) | 3.8 s |
| Mr. House | [Watch character demo 5](examples/dr-house/ditto_offline_20260905_081237_00004.mp4) | 3.0 s |

These are generated demonstration clips, not original recordings of the subjects.
Browse all selected media in [`examples/`](examples/). Only that curated directory
is published; source portraits, voice references, and working renders under
`inputs/` and `outputs/` stay local.

## What is in the repository

Application orchestration and service code is in `tools/`. Ditto is pinned as a
Git submodule under `vendors/Ditto`. Qwen is installed as a Python package and
its model is downloaded from Hugging Face on first use.

Large checkpoints, generated output, Python environments, and face/voice inputs
are deliberately excluded from Git.

## Requirements

- Linux x86-64
- An NVIDIA GPU supported by the selected Ditto TensorRT engines
- A compatible NVIDIA driver
- Docker Engine with the NVIDIA Container Toolkit
- Git and curl
- Roughly 30 GB of free disk space for the image, checkpoints, and model cache

The supplied Ditto engines target **Ampere or newer** GPUs. Other architectures
must generate compatible TensorRT engines from Ditto's ONNX checkpoints; see
`vendors/Ditto/README.md`.

Docker isolates the Python/CUDA user-space dependencies. It cannot replace the
host NVIDIA driver or make TensorRT engines portable across unsupported GPU
architectures.

## Quick start

Clone with the pinned Ditto source:

```bash
git clone --recurse-submodules <your-github-repository-url>
cd digital-clone
```

Download the pinned Ditto configuration and Ampere+ TensorRT engines. The
script resumes interrupted downloads and verifies every file:

```bash
./scripts/download-models.sh
```

Create a clone on the host (Python 3.10+):

```bash
python3 tools/clone_profiles.py create
```

The wizard asks for a clone name, portrait, voice WAV, and the exact transcript
of that reference recording. Enter a file path to copy it into the project,
`camera` to take a photo, `record` to record the microphone, or `write` to enter
the transcript. Finish a typed transcript by pressing Enter on an empty line (or entering `.`).
Camera capture uses Linux V4L2; microphone recording uses PulseAudio/PipeWire.
Both require host FFmpeg and access to the device. Recording asks for a duration
and starts after you press Enter. Supplied paths support `~`; enter paths without
shell quotes at the interactive prompt. Original files are left untouched.

You can prefill any fields and answer the remaining prompts:

```bash
python3 tools/clone_profiles.py create --name personal --image /path/to/portrait.png
python3 tools/clone_profiles.py list
```

Each clone is self-contained. Each run gets a separate output session:

```text
inputs/
└── personal/
    ├── clone.json
    ├── avatar.png
    ├── reference.wav
    └── reference.txt
outputs/
└── personal/
    └── session_<timestamp>/
        ├── audio/           # generated voice WAVs
        ├── videos/          # complete offline response MP4s
        ├── online/          # online model working files
        ├── session.mp4      # complete online recording, when enabled
        └── session.mp4.json # recording timing metadata
```

Only files relevant to the chosen mode are created. Inputs and outputs remain
ignored by Git. Clone names use lowercase letters, digits, hyphens and underscores.
Existing names are rejected, and cancelled creation leaves no partial clone.

The existing House assets are configured locally as `dr-house`:

```bash
./scripts/run-docker.sh --clone dr-house --mode online
```

Older House-generated audio and videos are preserved under
`outputs/dr-house/legacy/audio/` and `outputs/dr-house/legacy/videos/`.
New runs use separate session directories. All runs require `--clone NAME`.
Private clone profiles are local and are not included when cloning this repository.

Run the desktop container:

```bash
./scripts/run-docker.sh --clone personal --mode offline
```

The first run builds the image and downloads the Qwen model into
`.cache/huggingface`. Later runs reuse both caches.

If Docker reports permission denied for `/var/run/docker.sock`, configure your
normal user for Docker daemon access using Docker's official post-installation
instructions, then sign out and back in. The runner intentionally does not
silently elevate itself with `sudo`.

As a temporary alternative, preserve the desktop variables explicitly:

```bash
sudo --preserve-env=DISPLAY,XAUTHORITY,XDG_RUNTIME_DIR \
  ./scripts/run-docker.sh --clone personal --mode offline
```

Rebuild after changing application code or dependencies. Creating a clone or
replacing its portrait, voice WAV, or transcript does not require rebuilding:

```bash
./scripts/run-docker.sh --build --clone personal --mode offline
```

The build and runtime use the Linux host network for package and first-run Qwen
downloads. This avoids the common case where the host DNS works but Docker's
bridge resolver cannot reach Ubuntu, NVIDIA, PyTorch, PyPI, or Hugging Face. If
name resolution still fails, fix the Docker daemon's DNS configuration and
restart Docker before retrying.

## Improve an existing clone's voice

You can replace the voice reference without recreating the clone or changing its
portrait. This project uses one WAV and its exact transcript to build a voice
prompt at startup; it does not train a personal model or accumulate recordings.
Recording more takes helps you choose a better reference, but simply adding WAVs
to the folder has no effect. Longer recordings do not guarantee better results.
Qwen supports short reference clips; see the [official model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base).

Start with a clean, natural take of the paragraph below (roughly 20–30 seconds,
depending on your pace). This is a practical comparison sample, not a prescribed
model requirement or a guarantee of improved similarity.

> Hi, my name is Ayyoub. I enjoy building things, solving problems, and watching
> Real Madrid. What makes a good day? For me, it is learning something new and
> sharing a laugh with friends. Sometimes I speak slowly and think things through.
> Other times, I get excited—especially when we score a last-minute goal!

Use your ordinary accent and comfortable speaking voice. Let the question rise
naturally, pause briefly between sentences, and add a little genuine excitement
at the end. Avoid exaggerated acting, whispering, or shouting. No single sample
can capture every mood or nuance of your voice.

Record in a quiet room with little echo, keep a steady distance from the
microphone (try about 15–20 cm), and aim slightly off-axis to reduce breath pops.
Check that loud words do not distort. Avoid music, other speakers, reverb effects,
and aggressive noise reduction. Listen back before choosing a take. If you make
a mistake, redo the take or change the transcript to match exactly what you said.

### Record and compare a new take for ayyoub

Stop any running clone session. These commands run on the host and require FFmpeg
with PulseAudio/PipeWire capture support:

```bash
mkdir -p inputs/ayyoub/takes
ffmpeg -hide_banner -n -f pulse -i default -ac 1 -ar 24000 -c:a pcm_s16le \
  inputs/ayyoub/takes/reference-v2.wav
```

Speak the paragraph, then press `q` in the terminal to finish the WAV. The `-n`
option prevents overwriting an existing take; choose another filename to retry.
Keep only a short pause before and after the speech. Save the exact words spoken
in `inputs/ayyoub/takes/reference-v2.txt` (UTF-8). If you read the paragraph exactly,
copy its text without the Markdown quotation markers into that file.

Try the candidate without replacing the existing reference:

```bash
./scripts/run-docker.sh --clone ayyoub --mode offline \
  --reference /app/inputs/ayyoub/takes/reference-v2.wav \
  --reference-text-file /app/inputs/ayyoub/takes/reference-v2.txt
```

Compare against a normal run using the same test text, for example:
“Good morning! I have a new idea to share. Can we try it together?”
Offline mode makes it easier to assess the voice without phrase-splitting effects.
Try more than one generation before choosing; synthesis can vary between runs.

If you prefer the new reference, stop the app, back up the original pair, then
replace both files together:

```bash
backup_dir="inputs/ayyoub/takes/backup-$(date +%s%N)"
mkdir "$backup_dir"
cp inputs/ayyoub/reference.wav inputs/ayyoub/reference.txt "$backup_dir/"
cp inputs/ayyoub/takes/reference-v2.wav inputs/ayyoub/reference.wav
cp inputs/ayyoub/takes/reference-v2.txt inputs/ayyoub/reference.txt
```

Restart to rebuild the voice prompt from the new reference:

```bash
./scripts/run-docker.sh --clone ayyoub --mode online
```

No Docker rebuild is needed for this input-only update. All takes and backups
remain private under the Git-ignored `inputs/` directory. To revert, copy both
files from your backup directory back into `inputs/ayyoub/` and restart.

## Rendering modes

Both modes open one persistent window during initialization and show the avatar
when ready. Use the terminal to enter text and `/quit` to finish. The same window
is reused, preserving the size and position you choose during the session.

- `offline` renders a complete synchronized MP4, then plays it.
- `online` sends audio and animation frames through one synchronized media stream
  to the window, without waiting for a final MP4. It holds the latest frame while
  waiting for more media.

`live` remains a compatibility alias for `online`. Online mode experimentally
splits text at sentence boundaries or after 16 words. Each generated phrase is
sent to Ditto before generating the next, allowing voice generation and animation
to overlap. Qwen still returns a complete WAV per phrase; this is phrase-level
streaming, not token-level audio generation. Short phrases can change intonation,
and playback can pause if generation cannot keep up. Audio and frame timestamps
share the same media timeline; all phrases are included in the session recording.

Use `--chunk-words 8` for shorter chunks or `--chunk-words 0` to restore whole-input
voice generation. Offline rendering always uses the complete input.

```bash
./scripts/run-docker.sh --clone ayyoub --mode online --chunk-words 8
./scripts/run-docker.sh --clone ayyoub --mode online --chunk-words 0
```

Smaller chunks may start sooner but can increase pauses and change intonation.
The current checks cover phrase ordering, playback buffering, and recording muxing;
end-to-end latency and synchronization still need testing on the target GPU.


Offline mode is the recommended synchronized path:

```bash
./scripts/run-docker.sh --clone personal --mode offline
```

The full audio duration determines Ditto's exact 25 FPS frame count. Only after
Ditto finishes are the untouched audio timeline and rendered frames muxed into
one MP4. Playback waits for the file's real end-of-stream.

Online mode streams raw audio and frames through FFmpeg into the persistent MPV
window. The window opens during initialization, shows the avatar when ready, and
plays responses in place. Between responses it holds the latest generated frame.
Both desktop modes require MPV and use the same terminal controls and persistent
window. Moving or resizing it does not create a new window for the next response:

```bash
./scripts/run-docker.sh --clone personal --mode online
```

Online mode has lower initial latency, but its timing also depends on real-time
generation throughput, buffering, desktop scheduling, and GPU contention.

### Save online video and voice

Online mode saves the generated session, including synthesized voice, to a unique
`outputs/<clone>/session_<timestamp>/session.mp4` by default. Set a filename explicitly or
turn recording off:

```bash
./scripts/run-docker.sh --clone personal --mode online --record-video /app/outputs/personal/my-demo.mp4
./scripts/run-docker.sh --clone personal --mode online --no-record-video
```

Type `/quit` (or `/exit`) and wait for `Live recording saved` before closing the
terminal. Finalization drains queued frames and combines the timestamped voice
clips into the MP4. Existing destination files are rejected to prevent accidental
overwriting. This records the generated media timeline, including inter-utterance
gaps; it does not capture the desktop, microphone, or wall-clock time spent typing
and waiting for generation. A timing JSON sidecar stays beside the recording.

For repeatable playback, `--script-file PATH` reads one utterance per nonempty
line and exits after processing it. Put private scripts under `inputs/<clone>/`
and use `/app/inputs/<clone>/script.txt` inside Docker.

Finished videos remain under `outputs/<clone>/session_<timestamp>/`.
`examples/` contains selected public demo videos linked from the results section.
Copy only finished clips you want to publish there; private inputs and other
outputs remain ignored by Git.

For a machine without a desktop display, render files without playback:

```bash
CLONE=personal docker compose run --rm digital-clone
```

Generated files are written under `outputs/`.

## Visual styles

Offline output defaults to the `cinematic` treatment. Built-in options are:

```bash
./scripts/run-docker.sh --clone personal --mode offline --style natural
./scripts/run-docker.sh --clone personal --mode offline --style cinematic
./scripts/run-docker.sh --clone personal --mode offline --style warm
./scripts/run-docker.sh --clone personal --mode offline --style cool
./scripts/run-docker.sh --clone personal --mode offline --style noir
```

`natural` preserves Ditto's video stream without re-encoding it. Other presets
apply color, contrast, and optional vignette layers while retaining the same
audio timestamps.

Advanced compositions can supply any FFmpeg single-input video filter chain:

```bash
./scripts/run-docker.sh --clone personal --mode offline \
  --video-filter "eq=contrast=1.1:saturation=0.85,vignette=PI/4"
```

The custom chain overrides `--style`.

## Startup interface

The terminal and persistent video window display initialization progress while
Ditto and Qwen load. When both models are ready, the window replaces the startup
screen with the configured avatar image before the first `you>` prompt. Offline mode returns to the avatar after each response. Online mode keeps the
stream open and holds its latest generated frame between phrases and responses.

The terminal version uses an animated bar:

```text
Starting digital clone (offline mode)...
  [━━━━━━━━━━━━━━━ ● ──────────────]  50%  Loading voice model
```

Use `--no-progress` for plain CI logs or `--verbose` to expose the complete
Qwen and Ditto diagnostic streams.

## Desktop playback from Docker

`scripts/run-docker.sh` forwards the current X11 display and PulseAudio/PipeWire
runtime socket, then runs the container with your host UID. One long-lived MPV
process receives completed offline files or the online audio/video stream,
controlled through a local IPC socket. Its window is reused between responses. On a Wayland-only session, XWayland must be
enabled. Without `DISPLAY`, use offline mode: the script adds `--no-playback` and saves
complete videos. Online mode requires a desktop display. Both desktop modes require MPV; the supplied Docker image includes it.

If X11 rejects the local container connection, authorize the current local user
according to your distribution's X11 policy and run the command again. Avoid
globally disabling X server access control.

## Architecture and synchronization

```text
terminal text
    │
    ▼
Qwen3-TTS ── complete WAV ──► Ditto ── 25 FPS frames
                                      │
                                      ▼
                             aesthetic FFmpeg stage
                                      │
                                      ▼
                           synchronized MP4 + playback
```

Qwen and Ditto run in separate Python environments. This is intentional: Ditto
uses TensorRT 8.6 and cuDNN 8, while the Qwen process uses its own PyTorch CUDA
libraries. The launcher removes Ditto's explicit cuDNN override from Qwen but
retains NVIDIA runtime driver paths.

## Useful commands

```bash
make init          # initialize the Ditto submodule
make models        # download Ditto configs and Ampere+ engines
make build         # build the local image
make run CLONE=personal           # synchronized desktop/offline mode
make run-online CLONE=personal      # experimental online mode
make run-headless CLONE=personal  # offline rendering without a media window
```

Type `/quit` or `/exit` in the application to shut down both model services.

## Privacy and publication

Voice recordings and face images are biometric data. Confirm `.gitignore` is in
effect and inspect `git status` before every public push. Do not publish generated
media without the subject's consent.

This repository does not currently choose a license for its original integration
code. Select one before public release. Ditto and model/runtime components retain
their own terms; see `THIRD_PARTY_NOTICES.md`.
