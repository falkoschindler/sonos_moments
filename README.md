# Sonos Moments

<img src="https://raw.githubusercontent.com/falkoschindler/sonos_moments/main/screenshot.png"
    width="240" align="right" alt="Screenshot" />

This is a simple web application based on [SoCo](https://github.com/SoCo/SoCo/) and [NiceGUI](https://github.com/zauberzeug/nicegui) to control Sonos speakers in a local network.
Its main feature is to capture "moments", i.e. the current state of the speakers, and to restore them later.
This way, you can easily switch between different scenarios, e.g. your favorite radio station during breakfast in the kitchen, a relaxing playlist in the living room, or a party mix in the garden - all without having to use the original Sonos app.
Especially since their latest update, the Sonos app has become quite buggy and slow, so this is a lightweight alternative for those who just want to control their speakers.

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

## Usage

The web interface is quite simple and self-explanatory:

On the top panel there is a list of all available speakers.
You can control the volume of each speaker individually, mute/unmute it, and play/pause the current track.

You can capture the current state of the speakers by clicking the button on the top right.
A new moment will be added to the list below, with buttons to play, re-capture and delete it.
Feel free to rename the moment to something more meaningful.

## Vision

The most important feature of Sonos Moments, capturing and restoring the state of multiple speakers with a single click, is already implemented and works quite well.
But there are many more features that could be added in the future:

- control the volume of multiple speakers at once
- set alarms and timers
- pause and auto-resume after a predefined time (e.g. for a commercial break)
- allow copy-pasting a YouTube/Spotify/SoundCloud/Mixcloud link to play it on the speakers

More ideas are welcome, and contributions are highly appreciated!
