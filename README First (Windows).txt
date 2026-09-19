━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DRIVE CUTTER — READ ME FIRST  (Windows)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cut segments out of Google Drive or WeTransfer videos
without downloading the whole file. A 2-minute clip
from a 4-hour source pulls only ~2% of the bytes.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. SETUP  (one time, ~2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  a) Move this whole folder somewhere permanent —
     for example  C:\Users\<you>\Drive Cutter Windows
     or anywhere under Documents.

     DO NOT leave it in Downloads or on the Desktop
     inside OneDrive — Chrome may lose access to the
     helper if the folder gets moved or synced away.

  b) Double-click  install.bat.

     If Windows SmartScreen warns you ("Windows
     protected your PC"), click  More info  →
     Run anyway. It's just because the script isn't
     code-signed.

     The installer will:
       • install Python if you don't have it
       • download FFmpeg into  bin\
       • register the Chrome helper (native messaging)
       • open Chrome's Extensions page and this folder
         so you can Load Unpacked → pick the
         "extension" folder inside here

     To load the extension in Chrome:
       1. Turn on  Developer mode  (top-right toggle)
       2. Click  Load unpacked
       3. Select the  extension  folder inside here

  c) When it finishes, fully quit Chrome (close every
     window AND make sure it's not still running in
     the system tray) and open it again.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  2. HOW TO USE IT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ⚠ Drive Cutter is NOT an app you launch.
    It's a panel that appears inside Chrome when
    you're viewing a Drive or WeTransfer video.

  For a Google Drive video:

    1. In Google Drive, right-click the video and
       choose  Share  →  Copy link.
    2. Paste that link into a NEW Chrome tab and
       press Enter. (This opens the file's own
       preview page — that's the page the extension
       hooks into.)
    3. Once the video preview loads, the Drive
       Cutter panel appears bottom-right.
    4. Use the ⏱ buttons to grab the playhead, or
       type start/end as HH:MM:SS.
    5. Click  Cut.  When it finishes, click
       Download. You can queue multiple cuts —
       they run in parallel.

  For WeTransfer: just open the preview or download
  page normally; the panel shows up the same way.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  3. IF THE PANEL DOESN'T SHOW UP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • You're on the wrong URL. It must look like
      drive.google.com/file/d/…/view
    (Not a folder view, not "My Drive".)
  • You haven't fully quit and reopened Chrome
    since installing. Close every Chrome window,
    check the system tray, then relaunch.
  • The folder is in Downloads or a synced OneDrive
    location — move it somewhere stable and re-run
    install.bat.
  • Check chrome://extensions — "Drive Cutter"
    should be listed and enabled.

  Note: the Windows installer is less battle-tested
  than the Mac one. If something breaks, check
  logs\server.log first — that's where cut failures
  are recorded.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

That's it. For developer docs (how it works, env
vars, project layout), see  setup.md.
