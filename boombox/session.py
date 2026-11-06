"""One recording session: schedules stimuli against video frame 0 and writes all logs.

Output folder  <data_dir>/<YYYYMMDD_HHMMSS>_<AnimalID>_<Protocol>/  containing
  <base>.mp4          grayscale video with the microphone as its audio track
  <base>_audio.wav    microphone audio aligned so sample 0 = video frame 0
  <base>_trials.csv   one row per trial (times in ms from frame 0, frames 0-based)
  <base>_frames.csv   timestamp of every video frame, repeated frames flagged
  <base>_session.json experimenter, animal, protocol, schedule, calibration, camera settings
  <base>_events.log   readable timeline of the session
"""

import csv
import datetime as dt
import json
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from . import __version__, calibration, sysutil
from .audio import MicRecorder
from .camera import _NO_WINDOW, VideoRecorder, ffmpeg_path
from .stimuli import make_stimulus


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(s)).strip("-") or "NA"


class Session:
    def __init__(self, *, engine, camera, cal, protocol, trials, total_s, meta, settings,
                 uvc_values, log):
        self.engine, self.camera, self.cal = engine, camera, cal
        self.protocol, self.trials, self.total_s = protocol, trials, total_s
        self.meta, self.settings, self.uvc_values = meta, settings, uvc_values
        self.log_cb = log
        self.events_log = []
        self.state = "idle"     # idle | recording | finalizing | done | failed
        self.t0 = None
        self.stim_events = []   # (trial index, role, StimEvent, dbfs, cal status)
        self.mic = None
        self.recorder = None
        self.stopped_early = False
        self.result_text = ""

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base = f"{stamp}_{_safe(meta['animal_id'])}_{_safe(protocol['name'])}"
        self.folder = Path(settings["data_dir"]) / self.base
        self.started_at = dt.datetime.now().isoformat(timespec="seconds")

    # -- logging ---------------------------------------------------------
    def log(self, msg):
        t = f"{(time.perf_counter() - self.t0):9.3f} s" if self.t0 else "    --    "
        line = f"{dt.datetime.now():%H:%M:%S}  [{t}]  {msg}"
        self.events_log.append(line)
        self.log_cb(msg)

    def ms(self, perf):
        return None if perf is None or self.t0 is None else (perf - self.t0) * 1000.0

    # -- run -------------------------------------------------------------
    def start(self):
        self.folder.mkdir(parents=True, exist_ok=False)
        fs = self.engine.fs
        # Pre-render every stimulus so the start is not delayed later.
        rendered = []
        for i, tr in enumerate(self.trials):
            for role in ("prepulse", "pulse"):
                stim = tr.get(role)
                if stim:
                    dbfs, status, ok = calibration.stimulus_dbfs(self.cal, stim, stim["level_db"])
                    rendered.append((i, role, make_stimulus(stim, dbfs, fs), stim["onset_s"],
                                     dbfs, status))

        bg = self.protocol.get("background_noise_db")
        if bg is not None:
            dbfs, status, _ = calibration.stimulus_dbfs(self.cal, {"stimulus": "noise"}, bg)
            if self.engine.noise_target == 0:
                self.log(f"Background noise on: {bg:g} dB SPL ({dbfs:.1f} dBFS, {status})")
            self.engine.set_noise_dbfs(dbfs)

        if self.settings.get("mic_device"):
            self.mic = MicRecorder(self.settings["mic_device"], self.folder / "_mic_raw.wav")
            self.mic.start()
            self.log(f"Microphone recording: {self.settings['mic_device']} at {self.mic.fs} Hz")

        cam = self.camera
        self.recorder = VideoRecorder(self.folder / "_video.mp4", cam.width, cam.height, cam.fps,
                                      crf=self.settings["video_crf"],
                                      preset=self.settings["video_preset"])
        cam.recorder = self.recorder
        deadline = time.perf_counter() + 5
        while self.recorder.t0 is None:
            if time.perf_counter() > deadline or not cam.alive:
                cam.recorder = None
                self.recorder.close()
                if self.mic:
                    self.mic.stop()
                raise RuntimeError("No frames from the camera; recording not started.")
            time.sleep(0.005)
        self.t0 = self.recorder.t0
        self.state = "recording"
        self.log(f"Recording started (frame 0). {cam.width}x{cam.height} @ {cam.fps} fps, "
                 f"{len(self.trials)} trials, {self.total_s:.1f} s")
        for i, role, wave, onset_s, dbfs, status in rendered:
            ev = self.engine.schedule(wave, self.t0 + onset_s, {"trial": i, "role": role})
            self.stim_events.append((i, role, ev, dbfs, status))

    def elapsed(self):
        return 0.0 if self.t0 is None else time.perf_counter() - self.t0

    def poll(self):
        """Call regularly from the GUI. Returns True when the session should stop."""
        while self.engine.finished:
            ev = self.engine.finished.popleft()
            if ev.actual_perf is not None and not ev.cancelled and "trial" in ev.tag:
                tr = self.trials[ev.tag["trial"]]
                frame = self.recorder.frame_at(ev.actual_perf)
                late = f", {ev.late_s * 1000:.1f} ms LATE" if ev.late_s > 0.001 else ""
                self.log(f"Trial {tr['trial']} {ev.tag['role']} at {self.ms(ev.actual_perf):.1f} ms, "
                         f"frame {frame}{late}")
        if self.camera.error:
            self.log(f"CAMERA ERROR: {self.camera.error}")
            self.stopped_early = True
            return True
        return self.elapsed() >= self.total_s

    def next_trial(self):
        el = self.elapsed()
        for tr in self.trials:
            if tr["ref_time_s"] > el:
                return tr
        return None

    def last_stim_perf(self):
        times = [ev.actual_perf for _, _, ev, _, _ in self.stim_events if ev.actual_perf]
        return max(times) if times else None

    def stop(self, early=False):
        """Stop capture immediately (call from the GUI thread); then call finalize()."""
        self.stopped_early = self.stopped_early or early
        self.end_perf = time.perf_counter()
        self.camera.recorder = None
        for _, _, ev, _, _ in self.stim_events:
            if ev.pos == 0:
                ev.cancelled = True
        if self.mic:
            self.mic.stop()
        if early:
            self.log("Session stopped by user before the end of the protocol.")
        if not self.settings.get("keep_noise_after_session", True):
            self.engine.set_noise_dbfs(None)
            self.log("Background noise off.")
        self.state = "finalizing"

    # -- finalize -------------------------------------------------------------
    def finalize(self):
        try:
            self._finalize()
            self.state = "done"
        except Exception as e:      # keep whatever was written
            self.state = "failed"
            self.log(f"ERROR while saving: {e}")
            self._write_events_log()
            raise

    def _finalize(self):
        rec = self.recorder
        rc, err = rec.close()
        if rc != 0:
            raise RuntimeError(f"Video encoder failed: {err}")
        self.log(f"Video: {rec.n_frames} frames, {rec.n_duplicated} repeated for dropped camera "
                 f"frames in {len(rec.gaps)} gaps, {rec.skipped} extra camera frames discarded")
        for g in rec.gaps:
            self.events_log.append(f"    dropped: {g['missing']} frame(s) at frame {g['frame']} "
                                   f"({g['time_s'] * 1000:.1f} ms)")

        video_tmp = self.folder / "_video.mp4"
        video_final = self.folder / f"{self.base}.mp4"
        audio_final = self.folder / f"{self.base}_audio.wav"
        mic_fit = None
        if self.mic and self.mic.n_samples > 0:
            mic_fit = self.mic.clock_fit()
            self._write_aligned_audio(audio_final, mic_fit, rec.n_frames / rec.fps)
            cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(video_tmp), "-i", str(audio_final), "-map", "0:v", "-map", "1:a",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest",
                   "-movflags", "+faststart", str(video_final)]
            res = subprocess.run(cmd, capture_output=True, text=True, **_NO_WINDOW)
            if res.returncode == 0:
                video_tmp.unlink()
            else:
                self.log(f"Could not add audio to the MP4 ({res.stderr.strip()}); saved video without audio.")
                os.replace(video_tmp, video_final)
        else:
            os.replace(video_tmp, video_final)

        rows = self._trial_rows(mic_fit)
        self._write_trials_csv(rows)
        self._write_frames_csv()
        if self.mic and (self.folder / "_mic_raw.wav").exists():
            (self.folder / "_mic_raw.wav").unlink()
        self._write_session_json(rows)
        self._write_events_log()

        n_played = sum(1 for _, _, ev, _, _ in self.stim_events if ev.actual_perf)
        detected = [r for r in rows if r.get("pulse_mic_ms") not in (None, "")]
        self.result_text = (f"Saved to {self.folder}\n{n_played} stimuli played, "
                            f"{rec.n_duplicated} dropped frames"
                            + (f", {len(detected)} pulses detected by mic" if self.mic else ""))

    def _write_aligned_audio(self, path, fit, duration_s):
        """Resample the raw mic recording onto the video timeline (sample 0 = frame 0)."""
        a, b = fit
        raw, fs = sf.read(self.folder / "_mic_raw.wav", dtype="float32")
        n_out = int(round(duration_s * fs))
        src_idx = np.arange(raw.size, dtype=np.float64)
        with sf.SoundFile(path, "w", fs, 1, "PCM_24") as f:
            chunk = fs * 10
            for start in range(0, n_out, chunk):
                m = np.arange(start, min(start + chunk, n_out), dtype=np.float64)
                pos = (self.t0 + m / fs - a) / b
                f.write(np.interp(pos, src_idx, raw, left=0.0, right=0.0).astype(np.float32))
        self.mic_raw = raw
        self.mic_fs = fs

    def _detect_onset(self, stim, actual_perf, fit):
        """Measured onset (perf time) of a tone from the raw mic signal, or None."""
        if stim["stimulus"] != "tone" or fit is None or actual_perf is None:
            return None
        a, b = fit
        fs = self.mic_fs
        center = int(round((actual_perf - a) / b))
        lo, hi = center - int(0.05 * fs), center + int(0.15 * fs)
        if lo < 0 or hi > self.mic_raw.size:
            return None
        x = self.mic_raw[lo:hi].astype(np.float64)
        spec = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(x.size, 1 / fs)
        f0 = stim["freq_hz"]
        if f0 > fs / 2 - 500:
            return None
        spec[(freqs < f0 - 1500) | (freqs > f0 + 1500)] = 0
        y = np.fft.irfft(spec, x.size)
        win = max(1, int(0.001 * fs))
        env = np.sqrt(np.convolve(y ** 2, np.ones(win) / win, mode="same"))
        base = np.median(env[:int(0.03 * fs)]) + 1e-12
        peak_i = int(np.argmax(env))
        if 20 * np.log10(env[peak_i] / base) < 20:
            return None
        onset_i = peak_i - (stim["rise_ms"] + stim["plateau_ms"] / 2) * fs / 1000.0
        onset = a + b * (lo + onset_i)
        # Sound reaches the mic a few ms after the DAC; anything far outside that is not the tone.
        if not -0.005 <= onset - actual_perf <= 0.06:
            return None
        return onset

    def _trial_rows(self, fit):
        by_key = {(i, role): (ev, dbfs, status) for i, role, ev, dbfs, status in self.stim_events}
        rec = self.recorder
        rows = []
        for i, tr in enumerate(self.trials):
            ref_perf = self.t0 + tr["ref_time_s"]
            row = {"trial": tr["trial"], "trial_type": tr["type"],
                   "scheduled_ms": round(tr["ref_time_s"] * 1000, 3),
                   "scheduled_frame": rec.frame_at(ref_perf)
                   if ref_perf <= rec.frame_times[-1] + rec.period else ""}
            for role in ("pulse", "prepulse"):
                stim = tr.get(role)
                p = role + "_"
                if not stim:
                    for k in ("stimulus", "freq_hz", "level_db", "dbfs", "calibration",
                              "scheduled_ms", "actual_ms", "late_ms", "frame", "mic_ms",
                              "mic_frame", "mic_minus_actual_ms"):
                        row[p + k] = ""
                    if role == "prepulse":
                        row["lead_ms"] = ""
                    continue
                ev, dbfs, status = by_key[(i, role)]
                actual = ev.actual_perf if not ev.cancelled or ev.pos else None
                mic = self._detect_onset(stim, actual, fit)
                row.update({
                    p + "stimulus": stim["stimulus"],
                    p + "freq_hz": stim["freq_hz"] if stim["stimulus"] == "tone" else "",
                    p + "level_db": stim["level_db"],
                    p + "dbfs": round(dbfs, 2),
                    p + "calibration": status,
                    p + "scheduled_ms": round(stim["onset_s"] * 1000, 3),
                    p + "actual_ms": "" if actual is None else round(self.ms(actual), 3),
                    p + "late_ms": "" if actual is None else round(ev.late_s * 1000, 3),
                    p + "frame": "" if actual is None else rec.frame_at(actual),
                    p + "mic_ms": "" if mic is None else round(self.ms(mic), 3),
                    p + "mic_frame": "" if mic is None else rec.frame_at(mic),
                    p + "mic_minus_actual_ms": "" if mic is None else round((mic - actual) * 1000, 3),
                })
                if role == "prepulse":
                    row["lead_ms"] = tr["lead_ms"] if tr["lead_ms"] is not None else ""
            row["experimenter"] = self.meta["experimenter"]
            row["animal_id"] = self.meta["animal_id"]
            rows.append(row)
        return rows

    def _write_trials_csv(self, rows):
        with open(self.folder / f"{self.base}_trials.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def _write_frames_csv(self):
        rec = self.recorder
        with open(self.folder / f"{self.base}_frames.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["frame", "time_ms", "repeated_dropped_frame"])
            for i, (t, d) in enumerate(zip(rec.frame_times, rec.duplicated)):
                w.writerow([i, round((t - self.t0) * 1000, 3), d])

    def _write_session_json(self, rows):
        rec = self.recorder
        vol, muted = sysutil.output_volume()
        cam = self.camera
        data = {
            "software": f"Boom Box {__version__}",
            "started_at": self.started_at,
            "experimenter": self.meta["experimenter"],
            "animal": {k: v for k, v in self.meta.items() if k != "experimenter"},
            "stopped_early": self.stopped_early,
            "time_reference": "All times in ms from the start of video frame 0; frames are 0-based.",
            "protocol": self.protocol,
            "schedule": self.trials,
            "planned_duration_s": self.total_s,
            "recorded_duration_s": rec.n_frames / rec.fps,
            "video": {"file": f"{self.base}.mp4", "camera": cam.name,
                      "width": cam.width, "height": cam.height, "fps": cam.fps,
                      "frames": rec.n_frames, "repeated_frames": rec.n_duplicated,
                      "gaps": rec.gaps, "discarded_camera_frames": rec.skipped,
                      "camera_latency_ms": cam.latency_s * 1000,
                      "camera_controls": self.uvc_values,
                      "camera_controls_locked": self.settings.get("camera_controls_locked"),
                      "max_encoder_queue": rec.max_queue},
            "audio_output": {"device": self.engine.actual_device, "sample_rate": self.engine.fs,
                             "channel_mode": self.engine.channel_mode,
                             "system_volume": vol, "system_muted": muted,
                             "clipped_blocks": self.engine.clip_count,
                             "underflows": self.engine.underflow_count},
            "microphone": None if not self.mic else {
                "device": self.mic.device_name, "sample_rate": self.mic.fs,
                "file": f"{self.base}_audio.wav", "overflows": self.mic.overflow_count},
            "calibration": self.cal,
            "calibrated": calibration.is_calibrated(self.cal),
        }
        with open(self.folder / f"{self.base}_session.json", "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _write_events_log(self):
        with open(self.folder / f"{self.base}_events.log", "w") as f:
            f.write(f"Boom Box {__version__}  session {self.base}\n")
            f.write(f"Experimenter: {self.meta['experimenter']}   Animal: {self.meta['animal_id']}\n\n")
            f.write("\n".join(self.events_log) + "\n")
