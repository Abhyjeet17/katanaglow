# KatanaGlow user guide

## What is installed
- **The service** (`katanaglow`): starts at boot, owns the keyboard controller, draws the effects, and saves
  your settings in `/var/lib/katanaglow`. It runs as its own unprivileged account.
- **The settings window**: open "KatanaGlow" from the app menu, or run `katanaglow-gui`.
- **The command line**: `katanaglow-ctl`.

Closing the window does not stop the lighting. The service keeps running.

## Install, update, remove
    cd katanaglow                      # the project folder
    sudo bash deploy/install.sh           # installs or updates; your settings are kept
    sudo bash deploy/uninstall.sh         # removes it (add --purge to delete saved settings too)

After a first install, log out and back in once, so your account joins the `katanaglow` group.
That group only lets you send settings to the service. It does not give access to the keyboard or hardware.

## The settings window
- **Profiles**: pick a saved look and press Apply, or type a name and press Save current. A profile keeps the
  mode, colours, palette, speed, brightness and ripple look. It does not keep the colour balance, which
  stays as you set it. Up to 20 profiles.
- **Mode**: Off, Static, Wave, Breathe, Ripple. Only the controls that apply are shown.
- **Zone colours** (Static): one colour for each of the four zones.
- **Palette** (Wave, Breathe, Ripple): 1 to 8 colours. Wave blends across them, Breathe uses one per breath,
  Ripple uses the next one for each key press.
- **Ripple look**: Resting glow is the dim white shown between ripples (0 is off; the low end is fine
  control, because LEDs look brighter than their numbers). Tint lets you pick a coloured resting glow
  instead. Contrast makes ripple colours stand out over a bright resting glow: 0 is the plain blend,
  higher values let the colour take over sooner and dim the glow while a ripple passes.
- **Speed** and **Brightness** apply to every effect. Brightness is done in software.
- **Colour balance** (advanced): red, green and blue gains. Your keyboard's LEDs lean cool, so lowering
  green and blue a little (the default is 1.0, 0.8, 0.7) makes whites look neutral.

Changes apply as you make them and are remembered across restarts and shutdowns.

## Command line
    katanaglow-ctl status
    katanaglow-ctl off
    katanaglow-ctl static FF0000                        # one colour everywhere
    katanaglow-ctl static FF0000,00FF00,0000FF,FFFFFF   # one per zone, left to right
    katanaglow-ctl wave FF0040,00A0FF                   # also: breathe, ripple (palette optional)
    katanaglow-ctl brightness 0.5      katanaglow-ctl speed 1.5
    katanaglow-ctl gain 1,0.8,0.7      katanaglow-ctl base 202020      katanaglow-ctl punch 0.8
    katanaglow-ctl profiles
    katanaglow-ctl profile save "Night"      katanaglow-ctl profile load "Night"      katanaglow-ctl profile delete "Night"

Colours are six hex digits (RRGGBB), with or without a leading #.

## How it works, and what it can and cannot do
- The controller has **four zones**, not per-key lighting. Ripple is a pulse that spreads outward from the
  zone of the key you pressed, so it is coarse by nature.
- Wave and Breathe are drawn by the service, using only the static-colour commands, so the service must be
  running for them (it starts at boot).
- Nothing is ever written to the keyboard's own memory. A reboot always returns the keyboard to its
  saved lighting, and the service then re-applies yours. After suspend and resume the service re-applies
  your lighting too.
- Only two kinds of command are ever sent to the controller (select zones, set a static colour or off).
  Anything else is refused in code.

## Privacy and security
- The service reads the laptop keyboard **only while the mode is Ripple**. Each key press is turned into a
  zone number inside the service and thrown away. Key codes are never stored, logged, or sent to the window
  or the command line.
- The service has no network access, a read-only view of the system, no home-folder access, no special
  capabilities, and can open only raw HID and input devices.
- The control socket accepts small, strictly checked requests only, and only from members of the
  `katanaglow` group.

## Troubleshooting
    katanaglow-ctl status                       # is the service up, is the controller connected?
    systemctl status katanaglow                 # service state
    journalctl -u katanaglow -e --no-pager      # what the service logged

- **"service is not running"**: `sudo systemctl start katanaglow`, then check the journal.
- **"no permission to use the control socket"**: log out and back in after installing, or run
  `id` and check that `katanaglow` is in the list.
- **Controller "not connected" with "Permission denied"**: run `ls -l /dev/hidraw*` and look for the node owned
  by group `katanaglow`. If it shows owner-only access or has a `+` after the permissions, run
  `sudo setfacl -b /dev/hidrawN; sudo chmod 660 /dev/hidrawN` (replace N), or reboot. The installer does this itself.
- **Ripple does nothing**: `katanaglow-ctl status` should say the keyboard is "reading". If it says it cannot
  read the keyboard, check the journal.
- **Window does not open**: run `katanaglow-gui` in a terminal and read the message it prints.
- **Lighting looks wrong after suspend**: wait a couple of seconds, since the service re-applies it
  shortly after waking. Then check the journal for "resume detected".
- **Back to square one**: `sudo systemctl stop katanaglow` and reboot to return to the keyboard's own lighting.
