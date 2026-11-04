# ASR Recorder

Records acoustic startle response (ASR) and prepulse inhibition (PPI) sessions in mice on a Mac:
grayscale video from a USB camera, raised-cosine tone bursts through the headphone jack
(to an amplifier and speaker), constant background white noise, and a microphone track used to
check sync. Every stimulus is logged with the video frame it occurred in.

## Installing

Everything about installing is in **[INSTALL.md](INSTALL.md)**:

- [Quick install](INSTALL.md#quick-install): three steps for a Mac that already has Anaconda
- [Full step-by-step install](INSTALL.md#step-1-check-which-kind-of-mac-you-have): Anaconda, downloading the program, permissions, first-time settings
- [No password method](INSTALL.md#no-password-method): install and start from Terminal (`bash` + drag the file) when macOS asks for an administrator password
- [Installing a newer version](INSTALL.md#installing-a-newer-version-later): update without losing calibration, settings or data
- [Troubleshooting](INSTALL.md#troubleshooting)

## Starting the program each time

After the first-time setup, use either method below. That includes after closing the program, logging
out, or restarting the Mac. **You never need to open Anaconda or run `Setup_Environment.command` again**;
`ASR_Startle.command` switches on the program's environment by itself every time.

**Method 1: Double-click**
- Double-click **`ASR_Startle.command`** in the ASR folder (or its Dock icon, if you added one).
- Important:
  - If macOS asks for an **administrator password**, cancel and use Method 2 instead.
  - A Terminal window opens first. **Leave it open**; closing it quits the program.

**Method 2: Terminal (no password)**
- Open **Terminal** (⌘ + Space, type *Terminal*, press Return).
- Type `bash`, a space, then **drag `ASR_Startle.command`** from the ASR folder into the window and press Return.
- Important:
  - Put a **space after `bash`** before dragging the file in.
  - Drag the **file** `ASR_Startle.command`, not the ASR folder ("is a directory" means the folder was dragged).
  - "No such file or directory" means the space was missing or the file was moved; try again.
  - **Leave the Terminal window open** while the program runs.
  - The first-time installer runs the same way: `bash`, a space, drag in `Setup_Environment.command`.

**Both methods**
- Plug in the camera, USB microphone and amplifier **before** starting. If you plug the camera in later,
  click **Refresh list** on the Camera tab, then **Apply / restart camera**.
- Close the program with its own window (the red button). Saved settings, calibration and experimenter
  names are kept for next time.
- Only run `Setup_Environment.command` again after installing a newer version of the program, or if
  the program stops starting because something is missing.

## Before each day

- Plug the amplifier into the headphone jack. In **Settings**, choose *External Headphones* as the
  sound output and the USB microphone.
- Keep the Mac volume at the value used for calibration (the program warns if it changed).
- Turn on **Do Not Disturb** so notification sounds can't startle the animal.

## Calibration (Calibration tab)

Put a sound level meter where the mouse's head will be. For each frequency (and the white noise),
press **Play**, read the meter, and type the reading into *Measured dB SPL*. Press **Save calibration**.
The program then plays every stimulus at the dB SPL in the protocol, with one gain per frequency so
all frequencies are equally loud. Tones are calibrated by peak level, so a 10 ms burst has the same
peak as the continuous calibration tone. You can add other frequencies with *Add frequency*.

Until calibrated, levels are approximate and every log is marked `uncalibrated`.
"Loudest possible" shows the maximum each frequency can reach; if a protocol asks for more, the
session won't start (turn up the amplifier and recalibrate).

## Camera (Camera tab)

Default is **1280x720 at 30 fps**; 60 and 90 fps can be selected if the camera supports them
(*Show camera modes* lists what it supports). Adjust exposure, gain, focus etc. while watching the
preview, then tick **Lock camera settings**. Locked values are saved and re-applied at every session.
Turn auto exposure off and keep the exposure shorter than one frame (33 ms at 30 fps, 11 ms at 90 fps).

*Camera latency (ms)* is subtracted from each frame's arrival time. Leave it at 0 unless you
measure it (for example, film an LED that the program flashes or a hand clap the mic records).

## Protocols (Protocol tab)

- **ASR Standard** (built in, locked): 15 tones at 120, 157, 185, 218, 248, 260, 291, 334, 353, 388,
  419, 458, 486, 515 and 530 s; frequencies 12, 4, 16, 20, 8, 4, 20, 16, 12, 8, 8, 16, 4, 20, 12 kHz.
  Each is a 10 ms tone burst with a raised-cosine envelope (5 ms rise, 5 ms fall, no plateau).
  Level and background noise are editable after **Unlock for editing**; changes are saved under a
  new name and *Restore original ASR protocol* brings back the original.
- **New list**: any times and frequencies, typed in or generated (fixed or random gaps).
- **PPI**: pulse and prepulse stimuli, prepulse levels above background, lead intervals, trial counts,
  pulse-alone blocks, random inter-trial intervals. *Preview schedule* shows the exact trial list.

## Running a session (Session tab)

1. Choose the experimenter (*Add a name* the first time), enter the Animal ID and other details,
   choose the protocol.
2. Optionally press **Start background noise** for acclimation before recording.
3. **START SESSION**: a checklist of warnings appears, then a 5 s countdown. Frame 0 of the video is
   t = 0 for every time in the logs.
4. The session ends by itself after the last stimulus plus the protocol's padding (default 30 s).
   **STOP** ends early and still saves everything.
5. **Next animal** clears the animal fields and keeps everything else.

## Output files

Each session gets a folder `Data/YYYYMMDD_HHMMSS_AnimalID_Protocol/`:

| File | Contents |
|---|---|
| `<name>.mp4` | Grayscale H.264 video with the microphone as its audio track |
| `<name>_audio.wav` | Microphone audio, aligned so sample 0 = video frame 0 (full bandwidth) |
| `<name>_trials.csv` | One row per trial: scheduled and actual times (ms), video frame, level, dBFS, calibration status, mic-measured onset and frame, experimenter, animal |
| `<name>_frames.csv` | Time (ms) of every video frame; `repeated_dropped_frame = 1` marks frames repeated because the camera dropped one |
| `<name>_session.json` | Everything else: experimenter, animal details, protocol, schedule, calibration, camera settings, dropped-frame gaps, audio settings |
| `<name>_events.log` | Readable timeline |

Frames are numbered from 0. Times are in milliseconds from the start of frame 0.
`pulse_frame` is the frame being exposed when the sound left the computer; `pulse_mic_frame` is the
frame when the microphone heard it.

## Timing notes

- Stimuli are placed sample-accurately using the audio hardware clock (typically within 0.1 ms of
  schedule; `late_ms` reports any delay).
- If the camera drops frames, the previous frame is repeated so the MP4 stays at a constant rate in
  step with real time, and each repeat is logged.
- At 30 fps a frame lasts 33 ms, longer than the 10 ms tone; use 60/90 fps for finer timing.
