# iPod Drop

[简体中文](README.md) | [English](README.en.md)

A tool for importing and managing music on iPod nano 6th and 7th generation devices without iTunes.

Drop MP3 files or an entire music folder into the window to append them to an iPod in batches. Open **Manage Songs** to search, select, and delete tracks from the device. Deletions affect only the iPod; the original MP3 files on your computer are left untouched.

Current version: `0.2.0`. Detailed operating instructions are available in [使用说明.md](使用说明.md) (Chinese).

## Features

- **Batch import:** Drop multiple MP3 files or folders, including nested folders.
- **Exact duplicate detection:** Files are compared by SHA-256, so duplicate tracks are skipped automatically.
- **Song management:** Search by title, artist, or album, select multiple tracks, and delete them from the iPod.
- **No iTunes dependency:** Updates the iPod's SQLite library and signed `iTunesCDB` directly.
- **Automatic backups:** Backs up the complete library index before every actual import or deletion.
- **Transactional recovery:** Restores the previous state if a write fails or an interrupted transaction is found after a power loss.
- **Source files preserved:** Imports copy audio to the device, and deletions remove audio only from the device.
- **Cross-platform interface:** Native SwiftUI application for macOS and a local browser interface for Windows.
- **Windows driver assistant:** Guides users through installing Paragon's official 10-day HFS+ trial and supports existing Paragon or MacDrive volumes.

## Supported devices and formats

- iPod nano 6th and 7th generation models with a **SQLite library and HashAB signatures**.
- The currently tested device is an iPod nano 7th generation with USB product ID `0x1267` and firmware `1.0.4`.
- Only ordinary, DRM-free MP3 files are supported. FLAC, Apple Music subscription downloads, and other formats are not converted.
- Each MP3 must use parameters accepted by the iPod: sample rate up to 48 kHz and bitrate up to 320 kbps.
- Disable Finder, Music, or iTunes syncing for the device while importing. A later full-device sync by Apple software may overwrite manual changes.

## Getting started

### macOS

1. Open `iPod Drop.app` and connect the iPod.
2. Drop MP3 files or folders into the window, or choose **Select Songs…**.
3. To delete tracks, open **Manage Songs**, search for them, select them, and delete.
4. Select **Safely Eject** when finished.

The application uses Python 3.9 or newer from macOS or Homebrew as its engine runtime. The current build targets macOS 26.0 or newer. If Gatekeeper warns that the application is not notarized, verify its source and use **Open Anyway**.

### Windows x64

1. Fully extract `iPod-Drop-Windows-x64.zip` to a writable directory.
2. Double-click `Start iPod Drop.cmd`; the tool opens in your browser.
3. Connect the iPod, select **Refresh Devices**, and drop in songs.
4. Use the **Manage Songs** tab to delete tracks.

The package includes a Python 3.13 x64 runtime, so Python does not need to be installed separately. Do not run the application directly from inside the ZIP archive.

### Windows 32-bit

1. Fully extract `iPod-Drop-Windows32-x86.zip`.
2. Double-click `Start iPod Drop.cmd`.
3. On first launch, the tool downloads the official Python 3.13 32-bit embeddable runtime from python.org, falling back to Python 3.12 when necessary, and stores it in the package's `runtime32` directory. This requires one internet connection and verifies the PE architecture.
4. If no internet connection is available, install the official 32-bit Python 3.9 or newer first. The launcher will use it through `py -3-32`.

The 32-bit package can also run in the WoW64 environment on 64-bit Windows.

### Windows HFS+ driver

This iPod currently uses HFS+ (Mac OS Extended), which Windows cannot read or write natively. An additional file-system driver is required. The application includes a **Windows Driver** tab; you can also double-click `安装 Windows HFS+ 驱动.cmd`.

The driver assistant:

1. Requests administrator privileges.
2. Downloads `hfs14_win_trial.msi` from Paragon's official server.
3. Verifies its SHA-256 hash (`b229a05dac3e49e36e86ecf8e7c5c4926e5d8ecc76505162eacce86642e4d3bd`).
4. Installs the 10-day trial using `msiexec`.

If a full version previously installed through winget immediately asks for activation, uninstall it under **Settings → Apps**, then install the trial. After the trial expires, a Paragon license is required; the official price is approximately USD 20 at the time of writing and may change.

Alternatives:

- Use this tool on macOS for a free and reliable option.
- Boot from a Linux USB drive: the Linux kernel includes an `hfsplus` driver that can read and write HFS+. Back up the iPod before writing.
- Use MacDrive, another paid HFS+ driver. Confirm that it supports your version of Windows before purchasing.
- HFSExplorer, 7-Zip, the Boot Camp HFS+ driver, and similar free tools are generally read-only and cannot import or delete music.
- Reformatting the iPod as FAT32 allows native Windows access, but erases the device. Fully back it up and restore it through iTunes on Windows first.

Paragon's official trial installer: [hfs14_win_trial.msi](https://dl.paragon-software.com/demo/hfs14_win_trial.msi)

## Safe deletion

Deleting a track updates:

- the audio file;
- `Library.itdb`, `Locations.itdb`, `Dynamic.itdb`, and `Extras.itdb`;
- play statistics, playlist entries, and album, artist, and genre counts;
- the signed `iTunesCDB`.

Before deleting, the complete library index and audio files scheduled for deletion are moved into a transaction directory. The operation is committed only after all validation passes. On failure, the database and audio are restored. An unfinished transaction left by a power loss can be recovered with **Recover Previous Library**.

Source MP3 files on the computer are always preserved. Library backups are not complete backups of all audio; keep the original files for important music.

## Backup locations

- macOS: `~/Library/Application Support/iPod Drop/Backups/<device ID>/<timestamp>/`
- Windows: `%LOCALAPPDATA%\iPod Drop\Backups\<device ID>\<timestamp>\`

**View Backups** opens the backup directory. Old backups are not removed automatically.

## Building from source

### macOS

Requirements: Swift 6, Xcode Command Line Tools, and Python 3.9 or newer.

```bash
python3 Sources/build_macos.py
```

The output is `iPod Drop.app`. The build script copies the engine and bundled Mutagen and ipodsync libraries, then applies an ad hoc signature.

### Windows packages

A Windows package consists of `app/`, `runtime/`, and launcher scripts. See [packaging/README.md](packaging/README.md) for the directory layout and runtime configuration.

- x64: Python 3.13 embeddable **amd64** runtime.
- 32-bit: First-launch downloader in [packaging/windows32](packaging/windows32), or an existing 32-bit Python installation.

`Sources/engine.py`, `Sources/server.py`, and `Sources/windows.html` use only Python and HTML and do not require compiled extensions.

## Project layout

```text
Sources/
  engine.py             iPod library, CDB, signature, and transaction logic
  server.py             Local web server for Windows
  windows.html          Windows interface
  iPodDrop.swift        macOS SwiftUI interface
  build_macos.py        macOS build script
  drivers/              Windows HFS+ driver assistant
  vendor/               ipodsync and Mutagen
packaging/
  windows64/            x64 launchers and _pth template
  windows32/            32-bit runtime preparation scripts
licenses/               Third-party licenses
validation/             Test and validation records
使用说明.md              Detailed user guide (Chinese)
```

## Validation status

Validation completed on 2026-10-19:

- Deleted 2 tracks from a complete temporary copy of the connected device: the library went from 38 to 36 tracks, the SHA-256 hashes of all remaining audio stayed unchanged, and SQLite, playlist counts, and the `iTunesCDB` signature all passed validation.
- After an injected installation failure, the library and all audio were restored to their prior state.
- Recovery succeeded after simulating a power loss and rerunning `recover`.
- A test track was imported and then deleted successfully.
- The new macOS interface detected 38 tracks; the **Manage Songs** list, search, and selection worked correctly.
- The Windows engine and page script passed Python and JavaScript syntax checks.

Not yet validated:

- Playback on a physical iPod.
- The HFS+ driver and file locking on a physical Windows machine.
- Startup on a physical 32-bit Windows system.

See [validation](validation) for detailed records.

## Known limitations

- Supports only the SQLite/HashAB libraries used by iPod nano 6th and 7th generation devices, not older devices that use iTunesDB.
- Newly imported tracks do not receive artwork yet; existing artwork data is preserved.
- Changing an MP3's metadata changes its bytes, so the modified file is treated as a different track.
- Library updates write directly to the device's file system. Do not run iTunes or Music synchronization at the same time.
- The macOS application uses a local ad hoc signature and is not notarized by Apple.

## License

New code in this project is licensed under GPL-2.0-or-later. Third-party components retain their original licenses:

- [ipodsync](https://github.com/buldiei/ipodsync): MIT
- [dstaley/hashab](https://github.com/dstaley/hashab): Unlicense
- [PodBox](https://github.com/MilanMarocchi/podbox): MIT
- [Mutagen](https://mutagen.readthedocs.io/): GPL-2.0-or-later

See [LICENSE.txt](LICENSE.txt) and [licenses](licenses) for the complete texts.
