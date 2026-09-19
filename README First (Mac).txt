━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DRIVE CUTTER — READ ME FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cut segments out of Google Drive or WeTransfer videos
without downloading the whole file. A 2-minute clip
from a 4-hour source pulls only ~2% of the bytes.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. SETUP  (one time, ~2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  a) Move this whole folder somewhere permanent
     — for example your home folder (~/Drive Cutter Mac).
     DO NOT leave it in ~/Downloads. macOS revokes
     Chrome's access to Downloads across restarts and
     the extension will silently stop working.

  b) Open Terminal (Cmd+Space → "Terminal").

  c) Type  cd   then drag this folder into the window,
     press Return. Then run:

        ./install.sh

     (Windows: double-click  install.bat  instead.)

     The installer will:
       • install Python if you don't have it
       • download FFmpeg into  bin/
       • register the Chrome helper
       • open Chrome's Extensions page and this folder
         so you can Load Unpacked → pick the "extension"
         folder inside here

  d) When it finishes, QUIT Chrome fully (Cmd+Q, not
     just close the window) and open it again.


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
       press Return. (This opens the file's own
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
    since installing. Do Cmd+Q, then relaunch.
  • The folder is inside ~/Downloads — move it out
    and re-run  ./install.sh.
  • Check chrome://extensions — "Drive Cutter"
    should be listed and enabled.

  Logs live in  logs/server.log  — look there first
  when a cut fails.


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

That's it. For developer docs (how it works, env
vars, project layout), see  setup.md.
