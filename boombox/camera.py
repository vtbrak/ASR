"""USB camera capture (ffmpeg/AVFoundation) and constant-frame-rate MP4 recording.

Frames are read from ffmpeg as raw grayscale and timestamped on arrival with
time.perf_counter() (minus a configurable camera latency). The recorder keeps
the output locked to the wall clock: if the camera drops frames the previous
frame is repeated (and logged), so frame N in the MP4 is at N / fps seconds
and lines up with the audio track.
"""

import collections
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

TEST_PATTERN = "Test pattern (no camera)"
MODE_RE = re.compile(r"(\d+)x(\d+)@\[([\d.]+) ([\d.]+)\]fps")
RESOLUTIONS = {
    "A  800x600": "800x600",
    "B  1280x720 (recommended)": "1280x720",
    "C  1280x960": "1280x960",
    "D  1600x1200": "1600x1200",
    "E  1920x1080": "1920x1080",
    "F  1920x1200": "1920x1200",
}
FPS_CHOICES = [30, 60, 90]


def ffmpeg_path():
    p = Path(sys.prefix) / "bin" / "ffmpeg"
    return str(p) if p.exists() else (shutil.which("ffmpeg") or "ffmpeg")


def list_cameras():
    """Names of AVFoundation video devices, in index order (screens excluded)."""
    out = subprocess.run([ffmpeg_path(), "-hide_banner", "-f", "avfoundation",
                          "-list_devices", "true", "-i", ""],
                         capture_output=True, text=True, timeout=20).stderr
    names, in_video = [], False
    for line in out.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
        elif "AVFoundation audio devices" in line:
            break
        elif in_video:
            m = re.search(r"\[(\d+)\] (.+)$", line)
            if m and not m.group(2).startswith("Capture screen"):
                names.append(m.group(2).strip())
    return names


def camera_index(name):
    names = list_cameras()
    if name not in names:
        raise RuntimeError(f"Camera '{name}' not found. Connected: {', '.join(names) or 'none'}")
    return names.index(name)


def list_modes(name):
    """[(width, height, fps)] supported by the camera."""
    if name == TEST_PATTERN:
        return [(int(r.split("x")[0]), int(r.split("x")[1]), f)
                for r in RESOLUTIONS.values() for f in FPS_CHOICES]
    idx = camera_index(name)
    out = subprocess.run([ffmpeg_path(), "-hide_banner", "-f", "avfoundation",
                          "-framerate", "1000", "-video_size", "1x1", "-i", f"{idx}:none"],
                         capture_output=True, text=True, timeout=20).stderr
    modes = set()
    for m in MODE_RE.finditer(out):
        modes.add((int(m.group(1)), int(m.group(2)), float(m.group(4))))
    return sorted(modes)


def pick_framerate(modes, width, height, fps):
    """Exact framerate string the device accepts (e.g. 30.000030), or None if unsupported."""
    best = None
    for w, h, f in modes:
        if (w, h) == (width, height) and abs(f - fps) < 0.5:
            best = f
    return None if best is None else f"{best:.6f}"


def usb_cameras():
    """{camera name: (vendor_id, product_id)} for USB (UVC) cameras, from system_profiler."""
    try:
        out = subprocess.run(["system_profiler", "SPCameraDataType"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return {}
    cams, name = {}, None
    for line in out.splitlines():
        s = line.strip()
        if s.endswith(":") and line.startswith("    ") and not line.startswith("      "):
            name = s[:-1]
        m = re.search(r"UVC Camera VendorID_(\d+) ProductID_(\d+)", s)
        if m and name:
            cams[name] = (int(m.group(1)), int(m.group(2)))
    return cams


def default_camera(names):
    """Prefer an external USB camera over built-in/iPhone cameras."""
    usb = usb_cameras()
    for n in names:
        if n in usb:
            return n
    for n in names:
        if "FaceTime" not in n:
            return n
    return names[0] if names else TEST_PATTERN


class Camera:
    def __init__(self, name, width, height, fps, latency_ms=0.0):
        self.name = name
        self.width, self.height, self.fps = int(width), int(height), int(fps)
        self.latency_s = float(latency_ms) / 1000.0
        self.frame_bytes = self.width * self.height
        self.latest = None
        self.latest_time = None
        self.frame_count = 0
        self.recorder = None
        self.error = None
        self._times = collections.deque(maxlen=self.fps * 3)
        self._stderr = collections.deque(maxlen=40)
        self._proc = None
        self._stop = threading.Event()

    def _command(self):
        ff = ffmpeg_path()
        if self.name == TEST_PATTERN:
            src = ["-re", "-f", "lavfi", "-i",
                   f"testsrc2=size={self.width}x{self.height}:rate={self.fps}"]
        else:
            rate = pick_framerate(list_modes(self.name), self.width, self.height, self.fps)
            if rate is None:
                raise RuntimeError(f"{self.name} does not support {self.width}x{self.height} "
                                   f"at {self.fps} fps. Use 'Show camera modes' to see options.")
            src = ["-f", "avfoundation", "-pixel_format", "nv12", "-framerate", rate,
                   "-video_size", f"{self.width}x{self.height}",
                   "-i", f"{camera_index(self.name)}:none"]
        return [ff, "-hide_banner", "-loglevel", "warning", "-fflags", "nobuffer",
                "-flags", "low_delay", *src, "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]

    def start(self):
        cmd = self._command()
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.DEVNULL, bufsize=0)
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._read_frames, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def measured_fps(self):
        if len(self._times) < 10:
            return 0.0
        span = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / span if span > 0 else 0.0

    def _read_stderr(self):
        for raw in iter(self._proc.stderr.readline, b""):
            line = raw.decode(errors="replace").strip()
            if line and "AVCaptureDeviceTypeExternal is deprecated" not in line:
                self._stderr.append(line)

    def stderr_text(self):
        return "\n".join(self._stderr)

    def _read_frames(self):
        stdout = self._proc.stdout
        while not self._stop.is_set():
            buf = bytearray(self.frame_bytes)
            view, got = memoryview(buf), 0
            while got < self.frame_bytes:
                n = stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got < self.frame_bytes:
                break
            t = time.perf_counter() - self.latency_s
            frame = np.frombuffer(buf, np.uint8).reshape(self.height, self.width)
            self.latest, self.latest_time = frame, t
            self.frame_count += 1
            self._times.append(t)
            rec = self.recorder
            if rec is not None:
                rec.push(frame, t)
        if not self._stop.is_set():
            time.sleep(0.2)
            self.error = self.stderr_text() or "Camera stream ended unexpectedly."


class VideoRecorder:
    """Encodes pushed frames to H.264 MP4 at a constant frame rate locked to the wall clock."""

    def __init__(self, path, width, height, fps, crf=18, preset="veryfast"):
        self.path = str(path)
        self.width, self.height, self.fps = width, height, fps
        self.period = 1.0 / fps
        self.t0 = None
        self.frame_times = []     # perf time of each written frame
        self.duplicated = []      # 1 if the frame repeats the previous one (camera dropped)
        self.gaps = []            # {"frame", "time_s", "missing"}
        self.skipped = 0          # camera frames discarded because the camera ran fast
        self.max_queue = 0
        self._next_slot = 0
        self._last = None
        self._q = queue.Queue()
        cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}",
               "-r", str(fps), "-i", "pipe:0",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", self.path]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def _write(self, frame, t, dup):
        self.frame_times.append(t)
        self.duplicated.append(dup)
        self._q.put(frame)
        self.max_queue = max(self.max_queue, self._q.qsize())
        self._next_slot += 1

    def push(self, frame, t):
        if self.t0 is None:
            self.t0 = t
            self._last = frame
            self._write(frame, t, 0)
            return
        err = (t - self.t0) / self.period - self._next_slot
        if err > 1.5:
            missing = 0
            while err > 0.5:
                self._write(self._last, self.t0 + self._next_slot * self.period, 1)
                err -= 1
                missing += 1
            self.gaps.append({"frame": self._next_slot - missing,
                              "time_s": t - self.t0, "missing": missing})
        elif err < -1.5:
            self.skipped += 1
            return
        self._last = frame
        self._write(frame, t, 0)

    def _writer(self):
        while True:
            frame = self._q.get()
            if frame is None:
                break
            try:
                self._proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                break

    def close(self):
        self._q.put(None)
        self._thread.join()
        try:
            self._proc.stdin.close()
        except BrokenPipeError:
            pass
        self._proc.wait()
        err = self._proc.stderr.read().decode(errors="replace").strip()
        return self._proc.returncode, err

    @property
    def n_frames(self):
        return len(self.frame_times)

    @property
    def n_duplicated(self):
        return int(sum(self.duplicated))

    def frame_at(self, t):
        """Index of the frame being exposed at perf time t (-1 if before recording)."""
        if not self.frame_times:
            return -1
        return int(np.searchsorted(np.asarray(self.frame_times), t, side="right") - 1)
