# Publishing to GitHub

How the maintainer puts this folder on GitHub, and what must never go in it. Follow the
steps in order.

## Never commit

- `config.json` (your settings), `data/` (songs, recordings, loops), `assets/` (sounds)
- WAV, MP3, NPZ or ZIP files of any kind, SD card images or backups
- Wi-Fi names, passwords, keys, IP addresses or `.nmconnection` files

`.gitignore` blocks all of these. Never force-add an ignored file (`git add -f`).

## 1. Check your computer

Install [Git](https://git-scm.com/downloads) (or GitHub Desktop, which includes it). The
first time only, tell Git your name and the email address of your GitHub account:

```sh
git --version
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

You do not need to run the tests yourself. They need the starter sounds, which GitHub
generates and checks after every push (step 5).

## 2. Create the empty repository

On [github.com/new](https://github.com/new):

- **Repository name:** `RaveLearnDJTable`
- **Public** or **Private**, your choice
- Leave **Add a README**, **.gitignore** and **licence** all **off**. This folder already
  has them, and GitHub's copies would conflict.

Copy the repository URL GitHub shows, for example
`https://github.com/LifeOnAFarm/RaveLearnDJTable.git`.

## 3. Put the repository address in the guide

`docs/INSTALL.md`, step 3A, clones from this URL without the `.git` ending. Done for
this repository; change it only if the repository moves.

## 4. First commit and push

```sh
git init -b main
git add .
git status --short
```

Read the `git status` list before committing. It must show only source, docs and
scripts: no `config.json`, `data/`, `assets/` or audio files. Then:

```sh
git commit -m "First public release"
git remote add origin https://github.com/LifeOnAFarm/RaveLearnDJTable.git
git push -u origin main
```

GitHub asks you to sign in the first time, in your browser or with GitHub Desktop.

## 5. After the push

1. Open the repository's **Actions** tab and wait for **Tests** to finish green.
   It installs the starter-sound tools, generates the sounds and runs every test on
   Python 3.11 and 3.13.
2. Under **Settings → Code security**, turn on **Private vulnerability reporting**;
   [SECURITY.md](../SECURITY.md) points people there.
3. Optional: under **Releases**, create a release with a tag such as `v2026.10.09`
   and paste the newest section of [CHANGELOG.md](../CHANGELOG.md) as its notes.

## Later releases

1. Update the code, `docs/INSTALL.md` (if a setup step changed) and `CHANGELOG.md`.
2. Run the tests.
3. `git add .`, read `git status --short`, then `git commit` and `git push`.

## Release checklist

- [x] MIT licence approved by the project owner.
- [x] Personal config, recordings, song collections and generated media excluded.
- [x] Example config uses relative paths, no credentials, capture/platter off.
- [x] Install, wiring, controls, folder layout, sample replacement and updates documented.
- [x] Fresh card, copied table (INSTALL.md 3B): Raspberry Pi OS trixie, 9 October 2026.
  All 144 tests passed on the Pi, three clean reboots.
- [ ] A new table (INSTALL.md 3A, starter sounds) on a fresh Raspberry Pi OS Lite card.
- [ ] The test workflow has run green on GitHub.
- [x] Repository address in `docs/INSTALL.md` (https://github.com/LifeOnAFarm/RaveLearnDJTable).
