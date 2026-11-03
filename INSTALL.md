# Installing ASR Recorder on a Mac

No programming knowledge needed. Plan on about 30 minutes and an internet connection for the first install.

**You'll need:** a Mac with a headphone jack, the USB camera, the USB microphone, and the amplifier/speaker.

---

## Step 1. Check which kind of Mac you have
- Click the Apple menu () in the top-left corner, then **About This Mac**.
- If it says **Chip: Apple M1/M2/M3/M4…**, you have an **Apple Silicon** Mac.
- If it says **Processor: Intel…**, you have an **Intel** Mac.
- You'll need this in Step 2.

## Step 2. Install Anaconda (skip if it's already installed)
- Go to https://www.anaconda.com/download and download the **Mac** installer that matches your Mac from Step 1.
- Open the downloaded file and click through the installer, keeping all the default choices.
- **Not sure if it's already installed?** Open the **Terminal** app (press ⌘ + Space, type *Terminal*, press Return), type `conda --version` and press Return. If you see a version number, it's installed. If you see "command not found", install it.

## Step 3. Download the ASR Recorder program
- Go to https://github.com/vtbrak/ASR.
  - If the page says "404" or "not found", ask the lab member who owns the program to give your GitHub account access.
- Click the green **Code** button, then **Download ZIP**.
- Open your **Downloads** folder and double-click the ZIP file to unzip it. You'll get a folder named **ASR-main**.
- Move that folder to your **Desktop** and rename it **ASR**.

## Step 4. Run the one-time setup
- Open the **ASR** folder and **right-click** (or Control-click) **Setup_Environment.command**, then choose **Open**.
  - The first time, macOS warns that the file is "from an unidentified developer". Click **Open**.
  - If there's no Open button, go to **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to the file's name, and try again.
  - **Asked for an administrator password?** Use the **[No password method](#no-password-method)** at the end of this guide instead.
- A Terminal window opens and downloads everything the program needs. This takes 5–15 minutes.
- When it says **"Done. Press Return to close."**, press Return.

## Step 5. Plug in the equipment
- **Camera:** into a USB port.
- **Microphone:** into a USB port.
- **Amplifier:** a cable from the Mac's **headphone jack** to the amplifier input. Keep the amplifier's volume low for now.

## Step 6. Start the program
- In the **ASR** folder, double-click **ASR_Startle.command**.
  - If macOS blocks it, right-click → **Open**, as in Step 4.
- A Terminal window opens, followed by the ASR Recorder window.
- **Keep the Terminal window open.** Closing it quits the program.

## Step 7. Allow camera and microphone access
- The first time, macOS asks whether **Terminal** may use the **camera** and the **microphone**. Click **Allow** both times.
- Then **quit the program and start it again** (Step 6) so the permissions take effect.
- **No video, and no prompt appeared?** Go to **System Settings → Privacy & Security → Camera** and turn on **Terminal**. Do the same under **Microphone**. Then restart the program.

## Step 8. Set up the program (first time only)
- **Settings tab**
  - **Sound output:** choose **External Headphones**.
  - **Microphone:** choose your USB microphone. Click **Test mic** to check that it hears sound.
  - Click **Save settings and restart audio**.
- **Camera tab**
  - Choose your USB camera, keep **B 1280x720** and **30** fps, then click **Apply / restart camera**.
  - Adjust exposure, gain and focus while watching the video, then tick **Lock camera settings**.
- **Calibration tab:** once you have a sound level meter, follow the instructions at the top of that tab.
- **Session tab:** open the **Experimenter** list, choose **Add a name**, and type your name.

## Step 9. Make it easy to start next time (optional)
- Drag **ASR_Startle.command** onto the right-hand side of the **Dock** (next to the Trash) so you can start the program with one click.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| **"Could not find Anaconda"** | Anaconda isn't installed, or was installed somewhere unusual. Repeat Step 2, keeping the default choices. |
| **Setup mentions "Terms of Service"** | Open Terminal and run `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main` and then `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r`. Then repeat Step 4. |
| **"Permission denied" when opening a .command file** | Open Terminal and run `chmod +x ~/Desktop/ASR/*.command`. Then try again. |
| **Video window stays black** | See Step 7. Also unplug the camera, plug it back in, and click **Apply / restart camera**. |
| **No sound from the speaker** | Check that **Sound output** is **External Headphones** (Settings tab), the Mac isn't muted, and the amplifier is on. |
| **The camera isn't in the list** | Plug it in, then click **Refresh list** on the Camera tab. |

## Installing a newer version later
- Download and unzip the new version as in Step 3.
- **Before deleting the old ASR folder,** copy two folders from it into the new one:
  - **config**: your calibration, camera settings and experimenter names.
  - **Data**: your recorded sessions (unless you save them somewhere else).
- Run **Setup_Environment.command** again (Step 4) in case anything the program needs has changed.

---

## No password method

Use this if double-clicking a `.command` file asks for an **administrator password** (common on macOS 15 Sequoia for downloaded files). Starting the files from Terminal avoids that check, so no password is needed.

### 1. Open Terminal
- Press ⌘ + Space, type **Terminal**, and press Return.

### 2. Go to the ASR folder
- Type `cd` followed by **one space**. Don't press Return yet.
- Drag the **ASR** folder from Finder into the Terminal window. Its location appears after `cd `, for example:
  ```
  cd /Users/yourname/Desktop/ASR
  ```
- Press **Return**. Terminal is now "inside" the ASR folder.
- To check, type `ls` and press Return. You should see `ASR_Startle.command`, `Setup_Environment.command` and the other files.

### 3. Run the one-time setup
- Type `./` followed by the file name, then press Return:
  ```
  ./Setup_Environment.command
  ```
  - `./` means "the file in this folder".
  - Tip: type `./Set` and press **Tab**, and Terminal fills in the rest of the name.
- Wait for **"Done. Press Return to close."**, then press Return.

### 4. Start the program
- In the same Terminal window, type:
  ```
  ./ASR_Startle.command
  ```
- Keep the Terminal window open while you use the program. Then continue with Steps 7 and 8 above.

### Every time after that
- Open Terminal, type `cd ` and drag in the **ASR** folder, press Return, then type `./ASR_Startle.command` and press Return.

### If something goes wrong
- **"Permission denied":** type `bash` and a space before the file name, for example `bash ./ASR_Startle.command`.
- **"No such file or directory":** Terminal isn't in the ASR folder. Repeat step 2, making sure there's a space after `cd`.

### Optional: make double-clicking work without a password
- While Terminal is in the ASR folder (step 2), type this and press Return:
  ```
  xattr -dr com.apple.quarantine .
  ```
- This removes macOS's "downloaded from the internet" flag from the program's files, so double-clicking them works normally. It only changes files you own, so no password is needed.
