ASCII Camera
============

ascii camera thing!

you need obs!!

Run
---
1. Install Python 3.10 or newer.
2. From this folder:

   pip install -r requirements.txt
   python main.py

   Or double-click launch.bat.

Use as a camera in Discord / OBS
---------------------------------
Double-click launch.bat or main.py.

Discord: Settings > Voice and Video > Camera > OBS Virtual Camera.
OBS: add a Video Capture Device source and choose OBS Virtual Camera.
     You can also Window Capture the "ASCII Cam Output" window.

OBS Studio only needs to be installed once so the virtual camera driver
exists. It does not have to stay open.

The main app also has a Virtual cam button if you want the full controls
while still sharing to Discord.

Controls
--------
Start / Stop     Open or release the webcam.
Camera           Cycle available capture devices.
Resolution       Number of characters.
Density          Glyph size used when composing the frame.
Contrast         Tone curve around mid-gray.
Brightness       Lift or crush the mapping.
Frame rate       Capture/convert target. Default is 30.(kinda useless doesn't go above 20 lmao)
Copy             Copy the current ASCII frame as text.
Save             Write the current ASCII frame to a .txt file.
Fullscreen       Just Fullscreen don't be dumb!
Virtual cam      Share the ASCII feed as OBS Virtual Camera.

Keys: Space start/stop, F fullscreen, C copy, S save, Esc exit fullscreen or quit.

Notes
-----
If the camera does not start, close other apps using the webcam and allow
desktop apps to use the camera in Windows Privacy settings.
