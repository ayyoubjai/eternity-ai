import argparse
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import librosa
import numpy as np


PROTO = "@@CLONE@@"


def emit(obj):
    print(PROTO + json.dumps(obj), flush=True)


parser = argparse.ArgumentParser()

parser.add_argument("--ditto-root", required=True)
parser.add_argument("--source", required=True)
parser.add_argument("--data-root", required=True)
parser.add_argument("--cfg", required=True)
parser.add_argument("--output-dir", required=True)

parser.add_argument(
    "--fps",
    type=float,
    default=25.0,
)

parser.add_argument(
    "--gap-ms",
    type=int,
    default=350,
)

parser.add_argument(
    "--audio-delay-ms",
    type=int,
    default=0,
)

parser.add_argument(
    "--prebuffer-frames",
    type=int,
    default=10,
)

parser.add_argument(
    "--record-video",
    default=None,
    help="Record the paced live session to this MP4 path.",
)

args = parser.parse_args()


DITTO_ROOT = Path(args.ditto_root).resolve()

sys.path.insert(
    0,
    str(DITTO_ROOT),
)

os.chdir(DITTO_ROOT)


from stream_pipeline_online import StreamSDK


class LiveVideoWriter:

    def __init__(
        self,
        fps=25,
        audio_delay_ms=0,
        prebuffer_frames=10,
        record_path=None,
    ):
        self.fps = fps
        self.audio_delay = audio_delay_ms / 1000
        self.frame_period = 1.0 / fps
        self.prebuffer_frames = max(int(prebuffer_frames), 1)

        self.proc = None
        self.mux_proc = None
        self.video_write = None
        self.audio_write = None
        self.audio_packets = queue.Queue()
        self.audio_thread = None
        self.audio_error = None

        self.width = None
        self.height = None

        # Playback counter: incremented by the playback thread only after
        # a frame is sent at its scheduled time.
        self.frame_idx = 0

        self.last_frame_time = None

        self.frames = queue.Queue()
        self.closed = threading.Event()
        self.playback_thread = threading.Thread(
            target=self._playback_loop,
            daemon=True,
        )

        self.events = []
        self.events_lock = threading.Lock()

        self.record_path = (
            Path(record_path).resolve()
            if record_path
            else None
        )
        self.record_tmp_path = (
            Path(str(self.record_path) + ".tmp.mp4")
            if self.record_path
            else None
        )
        self.record_mux_path = (
            Path(str(self.record_path) + ".mux.mp4")
            if self.record_path
            else None
        )
        self.record_proc = None
        self.record_frames = queue.Queue()
        self.record_thread = None
        self.record_events = []
        self.record_error = None
        self.playback_end_frame = None

        self.playback_thread.start()


    def _open(self, frame):

        frame = np.asarray(frame)

        self.height, self.width = frame.shape[:2]

        video_read, video_write = os.pipe()
        audio_read, audio_write = os.pipe()

        mux_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-thread_queue_size", "512",
            "-f", "rawvideo",
            "-pixel_format", "rgb24",
            "-video_size", f"{self.width}x{self.height}",
            "-framerate", str(self.fps),
            "-i", f"pipe:{video_read}",
            "-thread_queue_size", "512",
            "-f", "f32le",
            "-ar", "16000",
            "-ac", "1",
            "-i", f"pipe:{audio_read}",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "rawvideo",
            "-pix_fmt", "rgb24",
            "-c:a", "pcm_f32le",
            "-max_interleave_delta", "0",
            "-flush_packets", "1",
            "-f", "nut",
            "pipe:1",
        ]

        try:
            self.mux_proc = subprocess.Popen(
                mux_cmd,
                pass_fds=(video_read, audio_read),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        finally:
            os.close(video_read)
            os.close(audio_read)

        player_cmd = [
            "ffplay",
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-framedrop",
            "-sync", "audio",
            "-autoexit",
            "-i", "-",
        ]

        self.proc = subprocess.Popen(
            player_cmd,
            stdin=self.mux_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.mux_proc.stdout.close()

        self.video_write = os.fdopen(
            video_write,
            "wb",
            buffering=0,
        )
        self.audio_write = os.fdopen(
            audio_write,
            "wb",
            buffering=0,
        )
        self.audio_thread = threading.Thread(
            target=self._audio_loop,
            daemon=True,
        )
        self.audio_thread.start()

        if self.record_path is not None:
            self.record_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            record_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-f", "rawvideo",
                "-pixel_format", "rgb24",
                "-video_size",
                f"{self.width}x{self.height}",
                "-framerate", str(self.fps),
                "-i", "-",
                "-an",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                str(self.record_tmp_path),
            ]

            self.record_proc = subprocess.Popen(
                record_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self.record_thread = threading.Thread(
                target=self._record_loop,
                daemon=True,
            )
            self.record_thread.start()

        print(
            f"Live window opened: "
            f"{self.width}x{self.height} "
            f"@ {self.fps} FPS",
            flush=True,
        )


    def show_initial(self, frame):
        self(frame)


    def schedule_audio(
        self,
        path,
        start_frame,
        end_frame=None,
        audio_samples=None,
    ):

        with self.events_lock:
            self.events.append(
                {
                    "path": str(path),
                    "start_frame": int(start_frame),
                    "queued_at": time.monotonic(),
                    "audio_samples": audio_samples,
                    "audio_end_frame": (
                        int(start_frame)
                        + max(
                            math.ceil(
                                len(audio_samples)
                                * self.fps
                                / 16000
                            ),
                            1,
                        )
                        if audio_samples is not None
                        else None
                    ),
                    "end_frame": (
                        int(end_frame)
                        if end_frame is not None
                        else None
                    ),
                }
            )

            self.record_events.append(
                {
                    "path": str(path),
                    "start_frame": int(start_frame),
                    "start_seconds": (
                        int(start_frame) / self.fps
                    ),
                    "audio_delay_ms": (
                        self.audio_delay * 1000
                    ),
                    "end_frame": (
                        int(end_frame)
                        if end_frame is not None
                        else None
                    ),
                }
            )

            if end_frame is not None:
                end_frame = int(end_frame)
                if (
                    self.playback_end_frame is None
                    or end_frame > self.playback_end_frame
                ):
                    # Frames after the last reserved audio interval are
                    # model flush padding during graceful shutdown.
                    self.playback_end_frame = end_frame

            self.events.sort(
                key=lambda x: x["start_frame"]
            )


    def _audio_loop(self):

        cursor = 0
        audio_write = self.audio_write
        silence = np.zeros(4096, dtype="<f4").tobytes()

        def write_silence(sample_count):
            remaining = sample_count
            while remaining > 0:
                count = min(remaining, 4096)
                audio_write.write(silence[:count * 4])
                remaining -= count

        try:
            while True:
                item = self.audio_packets.get()
                if item is None:
                    break

                start_sample, end_sample, samples = item

                if start_sample > cursor:
                    write_silence(start_sample - cursor)
                    cursor = start_sample
                elif start_sample < cursor:
                    samples = samples[cursor - start_sample:]

                if len(samples) > 0:
                    audio_write.write(
                        np.ascontiguousarray(samples).tobytes()
                    )
                    cursor += len(samples)

                if end_sample > cursor:
                    write_silence(end_sample - cursor)
                    cursor = end_sample

            final_sample = cursor
            if self.playback_end_frame is not None:
                final_sample = max(
                    final_sample,
                    round(
                        (
                            self.playback_end_frame / self.fps
                            + self.audio_delay
                        )
                        * 16000
                    ),
                )

            if final_sample > cursor:
                write_silence(final_sample - cursor)
        except (BrokenPipeError, OSError) as exc:
            self.audio_error = repr(exc)
            self.closed.set()
        finally:
            try:
                audio_write.close()
            except Exception:
                pass
            self.audio_write = None

    def _push_audio(self, event):

        samples = event.get("audio_samples")

        if samples is None:
            samples, _ = librosa.load(
                event["path"],
                sr=16000,
                mono=True,
            )

        samples = np.asarray(
            samples,
            dtype="<f4",
        )
        start_sample = round(
            (
                event["start_frame"] / self.fps
                + self.audio_delay
            )
            * 16000
        )
        end_frame = event.get("end_frame")
        end_sample = (
            round(
                (
                    end_frame / self.fps
                    + self.audio_delay
                )
                * 16000
            )
            if end_frame is not None
            else start_sample + len(samples)
        )

        self.audio_packets.put(
            (
                max(start_sample, 0),
                max(end_sample, 0),
                np.ascontiguousarray(samples).copy(),
            )
        )

    def _audio_event_is_due(self):

        with self.events_lock:
            return bool(
                self.events
                and self.events[0]["start_frame"]
                <= self.frame_idx
            )

    def _wait_for_audio_prebuffer(self, held_frames=0):

        if not self._audio_event_is_due():
            return False

        with self.events_lock:
            event = self.events[0]

        # This machine currently renders Ditto below 25 FPS. A small rolling
        # prebuffer therefore empties before an utterance ends and stalls the
        # multiplexed stream. Buffer the complete speech interval so the
        # player can consume it continuously at its true 25 FPS timeline.
        # Do not also wait for the trailing inter-utterance silence: those
        # frames are useful headroom and can finish rendering during speech.
        if self.closed.is_set():
            return False

        required_frames = self.prebuffer_frames
        if event.get("audio_end_frame") is not None:
            required_frames = max(
                required_frames,
                event["audio_end_frame"] - self.frame_idx,
            )

        return (
            self.frames.qsize() + held_frames
            < required_frames
        )

    def _check_audio_events(self):

        todo = []

        with self.events_lock:

            while (
                self.events
                and self.events[0]["start_frame"]
                <= self.frame_idx
            ):
                todo.append(self.events.pop(0))

        for event in todo:
            self._push_audio(event)

    def _write_frame(self, frame):

        if self.proc is None:
            self._open(frame)

        try:
            video_write = self.video_write
            if video_write is None:
                return False
            video_write.write(
                np.ascontiguousarray(frame).tobytes()
            )
        except (
            BrokenPipeError,
            OSError,
            ValueError,
        ):
            self.closed.set()
            return False

        if self.record_proc is not None:
            self.record_frames.put(frame)

        # This counter is updated by the playback thread, after pacing.
        self.frame_idx += 1
        self.last_frame_time = time.monotonic()
        return True

    def _record_loop(self):

        while True:
            frame = self.record_frames.get()

            if frame is None:
                break

            try:
                self.record_proc.stdin.write(
                    np.ascontiguousarray(frame).tobytes()
                )
                self.record_proc.stdin.flush()
            except (
                BrokenPipeError,
                OSError,
            ) as exc:
                self.record_error = repr(exc)
                break

    def _playback_loop(self):

        next_deadline = None

        while True:

            if (
                self.closed.is_set()
                and self.playback_end_frame is not None
                and self.frame_idx >= self.playback_end_frame
            ):
                break

            if self._wait_for_audio_prebuffer():
                time.sleep(0.005)
                continue

            try:
                frame = self.frames.get(timeout=0.1)
            except queue.Empty:
                if self.closed.is_set():
                    break
                continue

            if frame is None:
                break

            # schedule_audio() may run while this thread is blocked in
            # Queue.get(). Recheck with the dequeued frame included so the
            # first frame cannot bypass the utterance-sized prebuffer.
            while self._wait_for_audio_prebuffer(held_frames=1):
                time.sleep(0.005)

            now = time.monotonic()

            if next_deadline is None:
                next_deadline = now

            # Feed the shared-clock player at a stable 25 FPS. In particular,
            # never flush a burst of frames after a slow model call; that
            # creates buffering and late frames in the display pipeline.
            display_at = max(next_deadline, now)
            wait = display_at - now
            if wait > 0:
                time.sleep(wait)

            if self.proc is None:
                self._open(frame)

            self._check_audio_events()
            if not self._write_frame(frame):
                break

            next_deadline = display_at + self.frame_period

        if not self.closed.is_set():
            self._check_audio_events()

    def _finish_recording(self):

        if self.record_proc is None:
            return

        self.record_frames.put(None)

        if self.record_thread is not None:
            self.record_thread.join(timeout=30)

        try:
            self.record_proc.stdin.close()
        except Exception:
            pass

        try:
            self.record_proc.wait(timeout=30)
        except Exception:
            try:
                self.record_proc.terminate()
            except Exception:
                pass

        if (
            self.record_error is not None
            or self.record_proc.returncode != 0
            or not self.record_tmp_path.exists()
        ):
            print(
                "Live recording failed: "
                f"{self.record_error or self.record_proc.returncode}",
                file=sys.stderr,
                flush=True,
            )
            return

        sidecar_path = Path(
            str(self.record_path) + ".json"
        )
        sidecar_path.write_text(
            json.dumps(
                {
                    "fps": self.fps,
                    "audio_delay_ms": self.audio_delay * 1000,
                    "events": self.record_events,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if not self.record_events:
            os.replace(
                self.record_tmp_path,
                self.record_path,
            )
            print(
                f"Live recording saved: {self.record_path}",
                flush=True,
            )
            return

        mux_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(self.record_tmp_path),
        ]

        delayed_labels = []

        for index, event in enumerate(self.record_events, start=1):
            delay_ms = max(
                round(
                    event["start_seconds"] * 1000
                    + event["audio_delay_ms"]
                ),
                0,
            )

            mux_cmd.extend([
                "-i",
                event["path"],
            ])

            delayed_labels.append(
                f"[{index}:a]adelay=delays={delay_ms}:all=1"
                f"[a{index}]"
            )

        labels = "".join(
            f"[a{index}]"
            for index in range(1, len(self.record_events) + 1)
        )

        filter_complex = ";".join(delayed_labels) + ";" + (
            labels
            + f"amix=inputs={len(self.record_events)}:"
              "duration=longest:"
              "dropout_transition=0:"
              "normalize=0[aout]"
        )

        mux_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
        ])

        # Ditto flushes extra silent frames when it shuts down. Keep the
        # intentional final gap, but trim padding after the last reserved
        # audio interval. Include any explicitly configured audio delay.
        if self.playback_end_frame is not None:
            trim_seconds = (
                self.playback_end_frame / self.fps
                + self.audio_delay
            )
            mux_cmd.extend([
                "-t",
                f"{trim_seconds:.3f}",
            ])

        mux_cmd.append(str(self.record_mux_path))

        try:
            subprocess.run(
                mux_cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.replace(
                self.record_mux_path,
                self.record_path,
            )
            self.record_tmp_path.unlink(missing_ok=True)
            print(
                f"Live recording saved: {self.record_path}",
                flush=True,
            )
        except Exception as exc:
            print(
                "Live recording audio mux failed: "
                f"{exc!r}. Video is available at "
                f"{self.record_tmp_path}",
                file=sys.stderr,
                flush=True,
            )

    def __call__(
        self,
        frame,
        fmt="rgb",
    ):

        frame = np.asarray(frame)

        if frame.dtype != np.uint8:
            frame = np.clip(
                frame,
                0,
                255,
            ).astype(np.uint8)

        # Ditto may reuse its output buffer after this callback returns.
        # Copy it into a queue owned by the playback clock.
        self.frames.put(
            np.ascontiguousarray(frame).copy()
        )

    def close(self):

        # sdk.close() calls this after all Ditto workers have finished
        # producing frames. The sentinel therefore drains the queue first.
        self.closed.set()
        self.frames.put(None)

        # Queue every remaining timestamped event before ending the audio
        # pipe. The playback thread and audio writer then drain concurrently;
        # joining playback first can deadlock FFmpeg while it waits for audio.
        with self.events_lock:
            remaining_events = self.events
            self.events = []

        for event in remaining_events:
            self._push_audio(event)

        if self.audio_thread is not None:
            self.audio_packets.put(None)
            self.audio_thread.join(timeout=60)

            if self.audio_thread.is_alive() and self.audio_write is not None:
                try:
                    self.audio_write.close()
                except Exception:
                    pass
                self.audio_thread.join(timeout=5)

        self.playback_thread.join()

        if self.playback_thread.is_alive() and self.video_write is not None:
            try:
                self.video_write.close()
            except Exception:
                pass
            self.playback_thread.join(timeout=5)

        if self.audio_write is not None:
            try:
                self.audio_write.close()
            except Exception:
                pass
            self.audio_write = None

        if self.video_write is not None:
            try:
                self.video_write.close()
            except Exception:
                pass
            self.video_write = None

        if self.mux_proc is not None:
            try:
                self.mux_proc.wait(timeout=30)
            except Exception:
                try:
                    self.mux_proc.terminate()
                except Exception:
                    pass

        if self.proc is not None:
            try:
                self.proc.wait(timeout=30)
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass

        self._finish_recording()


class AudioFeeder:

    def __init__(
        self,
        sdk,
        writer,
        gap_ms,
        fps,
    ):

        self.sdk = sdk
        self.writer = writer
        self.fps = fps

        self.chunksize = (3, 5, 2)

        self.split_len = (
            int(
                sum(self.chunksize)
                * 0.04
                * 16000
            )
            + 80
        )

        self.step = (
            self.chunksize[1]
            * 640
        )

        self.step_seconds = (
            self.step / 16000
        )

        # The online config normally has seq_frames=80 and overlap_v2=70,
        # so valid_clip_len is 10. The first valid_clip_len feature frames
        # are consumed to initialize the streaming model; each later
        # feature frame produces one video frame.
        self.valid_clip_len = (
            self.sdk.audio2motion.valid_clip_len
        )
        self.feature_frames_submitted = 0
        self.audio_cursor_frame = 0

        self.gap_samples = int(
            gap_ms / 1000
            * 16000
        )

        # Initial context required by
        # Ditto online HuBERT processing.
        self.buffer = np.zeros(
            self.chunksize[0] * 640,
            dtype=np.float32,
        )

        # Audio timeline excludes the
        # initial model-only context.
        self.timeline_samples = 0

        # _feed_until_frame_target() may append temporary look-ahead silence
        # to flush the end of an utterance through Ditto.  Any part of that
        # silence which remains unconsumed in self.buffer must be replaced by
        # the next utterance.  Otherwise it becomes an unrecorded gap in the
        # animation timeline, making every message after the first late.
        self.synthetic_tail_samples = 0

        self.jobs = queue.Queue()

        self.stop = False

        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
        )

        self.thread.start()


    def submit(
        self,
        path,
        request_id,
    ):

        self.jobs.put(
            (path, request_id)
        )


    def _feed_available(self):

        submitted = 0

        while len(self.buffer) >= self.split_len:

            chunk = self.buffer[
                :self.split_len
            ].copy()

            t0 = time.perf_counter()

            self.sdk.run_chunk(
                chunk,
                chunksize=self.chunksize,
            )

            submitted += 1
            self.feature_frames_submitted += (
                self.chunksize[1]
            )

            self.buffer = self.buffer[
                self.step:
            ]

            # Feed Ditto approximately
            # at real audio speed instead
            # of flooding its GPU queues.
            spent = (
                time.perf_counter()
                - t0
            )

            delay = (
                self.step_seconds
                - spent
            )

            if delay > 0:
                time.sleep(delay)

        return submitted

    def _feed_until_frame_target(self, target_frame):

        # run_chunk() advances the streaming model by chunksize[1] feature
        # frames, but the first valid_clip_len frames are model warm-up.
        # Add silent model input until enough output frames can exist for
        # the audio interval we are about to play.
        current_output = max(
            self.feature_frames_submitted
            - self.valid_clip_len,
            0,
        )
        needed_output = target_frame - current_output

        if needed_output <= 0:
            return

        chunks_needed = math.ceil(
            needed_output / self.chunksize[1]
        )

        required_len = (
            self.split_len
            + (chunks_needed - 1) * self.step
        )

        padding_samples = max(
            required_len - len(self.buffer),
            0,
        )
        buffer_len_before_padding = len(self.buffer)

        if padding_samples > 0:
            self.buffer = np.concatenate(
                [
                    self.buffer,
                    np.zeros(
                        padding_samples,
                        dtype=np.float32,
                    ),
                ]
            )

        submitted = self._feed_available()

        # Each submitted chunk advances the persistent input buffer by step
        # samples.  Track only synthetic samples that were not advanced yet;
        # those are safe to replace when the next real utterance arrives.
        consumed_after_padding_started = max(
            submitted * self.step - buffer_len_before_padding,
            0,
        )
        self.synthetic_tail_samples = max(
            padding_samples - consumed_after_padding_started,
            0,
        )


    def _worker(self):

        while True:

            item = self.jobs.get()

            if item is None:
                break

            path, request_id = item

            try:

                wav, _ = librosa.load(
                    path,
                    sr=16000,
                    mono=True,
                )

                wav = np.asarray(
                    wav,
                    dtype=np.float32,
                )

                if self.synthetic_tail_samples > 0:
                    trim = min(
                        self.synthetic_tail_samples,
                        len(self.buffer),
                    )
                    self.buffer = self.buffer[:-trim]
                    self.synthetic_tail_samples = 0

                # Reserve a logical interval for this utterance. The
                # online model emits frames in bursts, so the current
                # writer position is not a reliable indication that the
                # previous utterance has finished.
                audio_frames = max(
                    math.ceil(
                        len(wav) * self.fps / 16000
                    ),
                    1,
                )
                gap_frames = math.ceil(
                    self.gap_samples * self.fps / 16000
                )

                start_frame = max(
                    self.writer.frame_idx,
                    self.audio_cursor_frame,
                )
                end_frame = (
                    start_frame
                    + audio_frames
                    + gap_frames
                )
                self.audio_cursor_frame = end_frame

                self.writer.schedule_audio(
                    path,
                    start_frame,
                    end_frame,
                    audio_samples=wav,
                )

                gap = np.zeros(
                    self.gap_samples,
                    dtype=np.float32,
                )

                payload = np.concatenate(
                    [
                        wav,
                        gap,
                    ]
                )

                self.buffer = np.concatenate(
                    [
                        self.buffer,
                        payload,
                    ]
                )

                self.timeline_samples += (
                    len(payload)
                )

                emit({
                    "type": "accepted",
                    "service": "ditto",
                    "id": request_id,
                    "duration": (
                        len(wav) / 16000
                    ),
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                })

                self._feed_available()

                # Ensure Ditto has enough input queued to render the
                # entire reserved interval. This is deterministic and
                # handles the model's normal 400 ms output bursts; a
                # quiet period must not be interpreted as completion.
                self._feed_until_frame_target(end_frame)

                # Do not wait for playback to reach end_frame here. Ditto's
                # streaming window can require samples from the next message
                # as look-ahead before it emits the final boundary frames.
                # Waiting here starves that next message and creates a long
                # freeze between utterances. The writer owns playback pacing;
                # this worker should keep the model input queue continuous.
                emit({
                    "type": "done",
                    "service": "ditto",
                    "id": request_id,
                    "frames": end_frame - start_frame,
                    "writer_frame": self.writer.frame_idx,
                    "target_frame": end_frame,
                    "render_queued": True,
                })

            except Exception as e:

                emit({
                    "type": "error",
                    "service": "ditto",
                    "id": request_id,
                    "message": repr(e),
                })


    def close(self):

        self.jobs.put(None)
        self.thread.join()

        # Flush remaining samples.
        if len(self.buffer) > 0:

            if len(self.buffer) < self.split_len:

                self.buffer = np.pad(
                    self.buffer,
                    (
                        0,
                        self.split_len
                        - len(self.buffer),
                    ),
                )

            self._feed_available()


output_dir = Path(
    args.output_dir
).resolve()

output_dir.mkdir(
    parents=True,
    exist_ok=True,
)


dummy_output = (
    output_dir
    / "_ditto_live_session.mp4"
)


print("Loading Ditto online...", flush=True)

sdk = StreamSDK(
    str(Path(args.cfg).resolve()),
    str(Path(args.data_root).resolve()),
)


print("Registering avatar...", flush=True)

sdk.setup(
    str(Path(args.source).resolve()),
    str(dummy_output),

    # Explicitly request continuous mode.
    online_mode=True,
)


# Ditto created its normal MP4 writer.
# Nothing has been submitted yet, so it is
# safe to close and replace it.
try:
    sdk.writer.close()
except Exception:
    pass


live_writer = LiveVideoWriter(
    fps=args.fps,
    audio_delay_ms=args.audio_delay_ms,
    prebuffer_frames=args.prebuffer_frames,
    record_path=args.record_video,
)

sdk.writer = live_writer


# Do NOT open the raw-video window from the source image.
# The source image resolution can differ from Ditto's rendered
# frame resolution. LiveVideoWriter opens the synchronized FFmpeg/ffplay
# stream when the first real Ditto frame arrives.
print("Live window will open on first rendered Ditto frame.", flush=True)


feeder = AudioFeeder(
    sdk,
    live_writer,
    args.gap_ms,
    args.fps,
)


emit({
    "type": "ready",
    "service": "ditto",
})


for line in sys.stdin:

    line = line.strip()

    if not line:
        continue

    try:
        msg = json.loads(line)
    except Exception:
        continue

    cmd = msg.get("cmd")

    if cmd == "quit":
        break

    if cmd == "play":

        feeder.submit(
            msg["path"],
            msg.get("id"),
        )


print("Stopping Ditto...", flush=True)

feeder.close()
sdk.close()

emit({
    "type": "stopped",
    "service": "ditto",
})
