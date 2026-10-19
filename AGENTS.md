# Notes for agents

A Sonos controller built on NiceGUI and SoCo, running on the same network as the speakers. Ideas for what comes next are collected in the [README](README.md#vision).

## Commands

```bash
uv run sonos-moments --port 8081   # start it (not python main.py, which turns the reloader on)
uv run pytest                      # tests, they run without speakers
uv run ruff check .                # lint, also runs as a pre-commit hook
```

The formatter (`ruff format`) is deliberately **not** enabled: it would upend the style of this project. Quotes are single, line length is 120.

## The speakers are real

There is no test environment. Every write goes to actual speakers in someone's home, and playback is audible. Therefore:

- Record the current state before a test (grouping, volume, mute, source, transport state) and restore it exactly afterwards.
- To test playback, pick a muted speaker rather than one that is currently playing.
- Changes to the grouping are harmless as long as nothing is playing — check first.
- Reads are safe. Much can be verified by reading alone, such as computing `plan()` against the live state without applying it.

If no unobtrusive way to test comes to mind, ask rather than starting the music.

## A Raspberry Pi runs alongside

The same application runs permanently as a systemd service on a Raspberry Pi Zero 2 W. Deployment and the unit are described in the [README](README.md#deployment); in short, `./deploy.sh`.

**Only one instance may talk to the speakers at a time.** Otherwise two processes hold `ZoneGroupTopology` subscriptions, and because of the pitfall below SoCo stops polling — both then see a grouping that is never updated again. So before testing locally against the same speakers:

```bash
ssh -4 "$SONOS_MOMENTS_HOST" 'sudo systemctl stop sonos_moments'
```

For anyone working on that machine: 417 MB of RAM, and under load it becomes unreachable for minutes while ping and TCP keep working. That is normal, it comes back on its own — do not pull the plug. Always detach longer-running commands (`nohup setsid … &`), or a dropped SSH connection kills them mid-run.

## Pitfalls that have cost time

- As soon as a `ZoneGroupTopology` subscription exists, SoCo stops polling the topology and expects the subscriber to feed the cache. Without that, the grouping stays frozen forever. See `System._read_topology`.
- In UPnP events, metadata is an empty string when there is nothing to report. `getattr('', 'title', '')` then returns the `str.title` method instead of the default. That is what `_text()` is for.
- After setting a new stream source, the speaker needs about a second before it accepts `play()`, otherwise `UPnP Error 701`.
- Two controllers at once are a problem locally as well: if the app is running while a script writes to the same speakers directly, `UPnP Error 402` and read timeouts come back that look like a bug in your own code. Stop the local instance before running such scripts.
- A refresh spans several `await`s. Nothing that replaces `state.groups` may interfere in between — that is what the lock in `System.refresh` is for.
- FAT32 carries no ownership of its own, so `chown` on the boot partition fails and the service cannot write its moments there. The mount options decide, and `vfat` fixes `uid`/`gid` at mount time: a `mount -o remount` silently keeps the old ones, it has to go all the way down and up. `setup.sh` does that.
- Raspberry Pi OS Trixie is customised through cloud-init (`user-data` and `network-config`), not through the `custom.toml` of the Bookworm era. A `custom.toml` is simply left lying there, and the board comes up with no user, no wifi and no SSH. In the image, sshd is disabled and the radio is blocked until a wifi country is set.
- `raspi-config` no longer switches the overlay through `boot=overlay`; it installs `overlayroot` and prepends `overlayroot=tmpfs` to the kernel command line. Checking for the old marker reports "off" on a system where it is on. What settles it is `findmnt /`, which says `overlay` once it has taken effect.

## Conventions

- Everything committed is in English: commit messages, code, comments and documentation alike.
- No network access in the render path. The UI reads exclusively from `SystemState`, everything blocking runs in a thread.
- Logic that can be tested without speakers belongs in a pure function — `plan()` with `tests/test_plan.py` is the model to follow.
- Nothing personal in the repository: no host names, user names, addresses from the local network, or anything else tied to one particular installation.
