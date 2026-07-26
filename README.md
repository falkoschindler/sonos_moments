# Sonos Moments

<img src="https://raw.githubusercontent.com/falkoschindler/sonos_moments/main/screenshot.png"
    width="240" align="right" alt="Screenshot" />

This is a simple web application based on [SoCo](https://github.com/SoCo/SoCo/) and [NiceGUI](https://github.com/zauberzeug/nicegui) to control Sonos speakers in a local network.
Its main feature is to capture "moments", i.e. the current state of the speakers, and to restore them later.
This way, you can easily switch between different scenarios, e.g. your favorite radio station during breakfast in the kitchen, a relaxing playlist in the living room, or a party mix in the garden - all without having to use the original Sonos app.
Especially since their latest update, the Sonos app has become quite buggy and slow, so this is a lightweight alternative for those who just want to control their speakers.

[![PyPI](https://img.shields.io/pypi/v/sonos-moments?color=dark-green)](https://pypi.org/project/sonos-moments/)
[![PyPI downloads](https://img.shields.io/pypi/dm/sonos-moments?color=dark-green)](https://pypi.org/project/sonos-moments/)
[![GitHub license](https://img.shields.io/github/license/falkoschindler/sonos_moments?color=orange)](https://github.com/falkoschindler/sonos_moments/blob/main/LICENSE)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/falkoschindler/sonos_moments)](https://github.com/falkoschindler/sonos_moments/graphs/commit-activity)
[![GitHub issues](https://img.shields.io/github/issues/falkoschindler/sonos_moments?color=blue)](https://github.com/falkoschindler/sonos_moments/issues)
[![GitHub forks](https://img.shields.io/github/forks/falkoschindler/sonos_moments)](https://github.com/falkoschindler/sonos_moments/network)
[![GitHub stars](https://img.shields.io/github/stars/falkoschindler/sonos_moments)](https://github.com/falkoschindler/sonos_moments/stargazers)

The official Sonos app for Android has an average rating of 1.2 stars on the Play Store.
Even before the latest disastrous update, it was sometimes a pain to use.
You want to start your morning routine with your favorite radio station in the kitchen, with a predefined volume, and all other speakers muted?
That will take some time with the official app, especially when every page takes a few seconds to load, every click a few retries to succeed, and every change a few seconds to take effect.
This sparked the idea for "Sonos Moments": capture recurring states of your speakers and restore them with a single click.
Maybe it is even the beginning of a new, lightweight, fast and open-source Sonos app?

## Infrastructure

Even though the first version of Sonos Moments was a mobile app implemented in C# using Xamarin.Forms a few years ago, it was time for a rewrite in Python.
The upcoming web UI framework [NiceGUI](https://github.com/zauberzeug/nicegui) seemed like a perfect fit for this project, allowing for a much faster development cycle than with a mobile app.
And we can use the existing [SoCo](https://github.com/SoCo/SoCo/) library to interact with the Sonos speakers, avoiding the need for reinventing the wheel.
The only downside is that the web app needs to run on a device in the same network as the Sonos speakers, but that is a limitation we can live with.
An inexpensive Raspberry Pi Zero or similar device should do the job just fine.
Another advantage of this setup is that we can easily store shared state on the server, e.g. the list of moments, without having to deal with synchronization issues between multiple clients.

## Getting Started

To run Sonos Moments, you need a device in the same network as your Sonos speakers.
This can be a Raspberry Pi, a laptop, or any other device that can run Python.

1. Install:

   ```bash
   pip install sonos-moments
   ```

2. Run:

   ```bash
   sonos-moments
   ```

The web interface will automatically open in your default browser at `http://localhost:8080`.
If you want to access it from another device, you need to replace `localhost` with the IP address of the server, which is printed in the console when the server starts.

Run `sonos-moments --help` to see all available options, e.g. to change the port.

### On your phone

Sonos Moments ships a web app manifest, so it can live on the home screen instead of in a browser tab.
On iOS, open the address in Safari and choose "Add to Home Screen": the app then starts full screen, without browser chrome, and gets its own icon.
Android requires HTTPS for a real installation, which a server in your local network usually does not have — there, "Add to Home screen" creates a shortcut that opens in the browser.

## Deployment

For permanent operation, Sonos Moments is best run as a systemd service on a small always-on machine like a Raspberry Pi Zero 2 W.

### Preparing the card

Flash **Raspberry Pi OS Lite (64-bit)** with the Raspberry Pi Imager - the Lite image, because the machine runs headless and a Zero 2 W only has about 417 MB of usable RAM.
Open the settings (the gear, or `Cmd+Shift+X`) and preconfigure hostname, user, your SSH public key, wifi SSID with country, and the timezone.
Without that, a headless board never joins the network and the card has to come out again.

Note that a Zero 2 W speaks 2.4 GHz only, and its antenna is etched onto the board with no connector for an external one - a metal enclosure is enough to keep it off the network for good.

The first boot resizes the filesystem and generates host keys, which takes its time on this hardware; give it 15 to 20 minutes before assuming something is wrong.
Then run the one-time setup from your machine:

```bash
./setup.sh [user@host]
```

It installs uv, creates the service, points the NiceGUI storage at the boot partition (see below), and reduces how much gets written to the card.
The unit it writes is `/etc/systemd/system/sonos_moments.service`:

```ini
[Unit]
Description=Sonos Moments
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/<user>/sonos_moments
User=<user>
Group=<user>

ExecStart=/home/<user>/sonos_moments/.venv/bin/sonos-moments --port 8081

Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

`ExecStart` points at the virtualenv directly instead of going through `uv run`, which would try to reach the network on every start - an unnecessary source of failure while booting, when the network may not be up yet.

### Surviving the plug being pulled

An SD card does not take kindly to being switched off mid-write, and a machine that lives behind a socket will be switched off eventually.
The fix is the overlay filesystem that Raspberry Pi OS ships with:

```bash
sudo raspi-config nonint enable_overlayfs && sudo reboot
```

The root filesystem is then mounted read-only with a tmpfs layered on top, so the card is never written to again and the plug can be pulled at any time.
This is not a read-only system in the painful sense - logs, `app.storage` and temporary files all keep working normally, they just do not survive a reboot.
What they do consume is RAM, which is why `setup.sh` limits the journal to 16 MB in memory.

Two consequences worth knowing:

- The moments would be lost on every reboot, so `setup.sh` symlinks `.nicegui` to a directory on the boot partition, which stays writable.
  The card is then only ever written to in the instant a moment is saved.
- A deployment does not survive a reboot either.
  Turn the overlay off, deploy, turn it back on:

  ```bash
  sudo raspi-config nonint disable_overlayfs && sudo reboot
  ```

Subsequent deployments are handled by `deploy.sh`, which syncs the working tree with [livesync](https://github.com/zauberzeug/livesync), updates the dependencies and restarts the service:

```bash
./deploy.sh [user@host]
```

It waits for the service to answer on port 8081 and points at the journal if it does not.
Note that `.syncignore` keeps `.venv/` out of the transfer - the target builds its own for its architecture.

While developing, and with the overlay turned off, `livesync` can also keep watching and restart the service on every change:

```bash
livesync . <user>@<host>:sonos_moments --on-change "sudo systemctl restart sonos_moments"
```

Only one instance should talk to the speakers at a time.
As soon as a `ZoneGroupTopology` subscription exists, SoCo stops polling the topology, so a second instance can leave the first one with a stale view.
Stop the service before running a local copy against the same speakers.

## Usage

The web interface is quite simple and self-explanatory:

Everything is on a single screen.
The main area shows one card per group of speakers with what is playing there, buttons to play, pause and stop it, a menu to pick one of your Sonos favorites, and a menu to change which rooms belong to the group.
Below that, each speaker has its own row to control volume and mute.

The bar at the bottom holds your moments.
Tapping one restores it; the arrow next to it opens a menu to edit, re-capture or delete it.
The button on the right captures the current state of the speakers as a new moment.

Both lead into the same editor, where a moment is put together rather than only recorded: give it a name, pick the rooms of each group, choose a source from your Sonos favorites and set the volume of every speaker.
So you can build a moment for tomorrow morning without waking anyone up tonight.

## Vision

The most important feature of Sonos Moments, capturing and restoring the state of multiple speakers with a single click, is already implemented and works quite well.
But there are many more features that could be added in the future:

- control the volume of multiple speakers at once
- set alarms and timers
- pause and auto-resume after a predefined time (e.g. for a commercial break)
- allow copy-pasting a YouTube/Spotify/SoundCloud/Mixcloud link to play it on the speakers

More ideas are welcome, and contributions are highly appreciated!
