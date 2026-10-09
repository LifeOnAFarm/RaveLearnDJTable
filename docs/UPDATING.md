# Updating and recovery

Keep personal audio and settings separate from code. The public repository's
`.gitignore` excludes `config.json`, `data/`, `assets/` and `.venv/`; an ordinary
source update should not replace them. Never use `git clean -fdx`: it removes
ignored recordings, sound packs and the Python environment.

These instructions use the source checkout at `~/PiDJTable` and installed
copy at `/opt/PiDJTable`, as in INSTALL.md. Do not update during capture or loop
preparation. This is a manual update procedure, not an automatic updater.

## Before an update

1. Read the release notes for required config/dependency changes.
2. Download/update the source checkout before stopping the toy. If published:

```sh
cd ~/PiDJTable
git status --short
git pull --ff-only
```

If you have local source edits, preserve/review them before pulling. Do not
use a reset to discard them. Until a repository URL exists, use a new downloaded
source folder and substitute its path for `~/PiDJTable` below.

3. Stop both services and make a complete backup outside the installation:

```sh
sudo systemctl stop djtable djtable-web
task_backup="/var/backups/djtable-$(date +%Y%m%d-%H%M%S)"
sudo mkdir -p "$task_backup"
sudo tar --exclude=./.venv --exclude=./.git -czf "$task_backup/install.tar.gz" -C /opt/PiDJTable .
sudo cp /opt/PiDJTable/requirements.txt "$task_backup/requirements.txt"
/opt/PiDJTable/.venv/bin/pip freeze | sudo tee "$task_backup/python-packages.txt" >/dev/null
echo "$task_backup"
```

This includes code, `config.json`, uploads, custom assets, saved voice, loop
layers/Undo and remixes. The virtual environment is excluded; package versions
are recorded separately. Ensure sufficient free storage and retain the backup
path. A backup on the same SD card does not protect against SD failure: copy it
to another device too. Do not publish it; it can contain personal media/settings.

## Install the new source

From the public checkout, copy **source only**. These names are deliberately
explicit; do not copy the entire private workspace or overwrite config/assets:

```sh
cd ~/PiDJTable
sudo cp -a djtable tools tests deploy examples docs /opt/PiDJTable/
sudo cp -a README.md CHANGELOG.md CONTRIBUTING.md SECURITY.md LICENSE config.example.json requirements.txt /opt/PiDJTable/
cd /opt/PiDJTable
sudo sh deploy/install-services.sh
sudo -u djtable .venv/bin/python -m unittest discover -s tests -v
sudo -u djtable .venv/bin/python -m djtable --check-assets
sudo -u djtable .venv/bin/python tools/check_media.py
sudo systemctl start djtable djtable-web
systemctl status djtable djtable-web --no-pager
journalctl -u djtable -n 60 --no-pager
```

The copy assumes an additive update with the same module layout. If release
notes remove/rename Python modules, follow their migration instructions;
`cp` does not delete obsolete source files. The installer sets permissions and
refreshes service units without starting services or touching boot/packages.
Tests create/remove their own temporary data; saved user media is separate.
For a big dependency change, rebuild a new virtual environment separately and
retain the old one until the new version passes checks. Do not unhold networking
packages or run a blanket OS upgrade as part of a source update.

Do **not** regenerate all starter assets on every update. The generator preserves
existing files, including old instrument archives. If a release requires new
built-in sounds, back up/move only the named archives/files and run the generator
with audio stopped. Your uploaded key overrides still take priority. See
[SAMPLES.md](SAMPLES.md#5-prompt-and-built-in-sustained-instruments).

Open the webpage, check the current activity/theme, and listen to keys, songs
and a microphone recording. A passing software check is not a sound-quality test.

## Recover from a failed update

Stop both services. Restore the snapshot taken immediately before the update
using its actual backup path, then reinstall the saved service units:

```sh
sudo systemctl stop djtable djtable-web
sudo tar -xzf /var/backups/djtable-YYYYMMDD-HHMMSS/install.tar.gz -C /opt/PiDJTable
cd /opt/PiDJTable
sudo sh deploy/install-services.sh
sudo systemctl start djtable djtable-web
```

Restore only to the intended `/opt/PiDJTable` directory. Extraction overwrites
snapshot paths but does not remove files introduced later; if new source
modules conflict, move the current `djtable/` directory to a separate backup
before extracting, as directed by that release. If you changed dependencies,
restore/recreate the previous environment as well. Restoring the full snapshot
also restores media/settings to backup time, replacing subsequent recordings.
Choose a source-only recovery if you need to retain newer personal audio.
