# Packaging the Zenodo Upload (maintainers) and scratchpad

> **Note:** This document was originally internal to the Lab. It is included in this release so researchers can see how the data was packaged for Zenodo and why those decisions were made.

> Author's Note: This was only included in case it was useful if people wanted to see how the Lab packaged it for release.

How to split ~9.5 GB into a package that people can actually use and download. This is a document meant for BioSEL or anyone extending those works; most as in the vast majority of the users should not need to use this.

The package is **6 top-level folders plus a handful of root files**:

```
Code/  Hardware/  Raw_Data/  Curated_Data/  Dataset/  Visualization/
README.md   01_GETTING_STARTED.md   pyproject.toml   uv.lock   requirements.txt
LICENSE   LICENSE-MIT   LICENSE-CERN (cern_ohl_p_v2.txt)   BioSEL.code-workspace
```

---

## The design consideration: one zip per top-level folder, root files kept flexible

Zip each of the 6 folders separately. Upload the root files **unzipped**.

| Upload                                          | Size              | Why it is its own file                                                                                        |
| ----------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------- |
| `Raw_Data.zip`                                  | large             | Not needed to _start_, but this plus `Curated_Data.zip` is the flagship portion the results are derived from. |
| `Curated_Data.zip`                              | large             | Needed only to re-run the pipeline. Most people will want this                                                |
| `Dataset.zip`                                   | ~4.5 GB (largest) | The finished PKL and summary tables: what most people actually want. Mandatory for download                   |
| `Code.zip`                                      | small             | The python pipeline to load the data for BioSEL-PULSE                                                         |
| `Visualization.zip`                             | small             | The figure renderer for people to view the hysteresis and other useful metrics.                               |
| `Hardware.zip`                                  | small             | Rig, STEP files, Arduino sketches.                                                                            |
| `README.md`, `01_GETTING_STARTED.md`, licences  | KB                | **Flexible**, so they are readable on the record page without downloading anything.                           |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | KB                | **Flexible.** See the warning below.                                                                          |

### Why the environment files must be Flexible

`uv sync` runs at the root directory alongside `pyproject.toml` and `uv.lock`. This was meant to avoid having separate enviroments between Code/BioSEL-PULSE and Visualization (In the event that people download just the Visualization but not the Code)

### Why not one big 9.5 GB zip

It forces every user to download all 9.5 GB, including the person who only wanted `all_results.pkl`, and a single interrupted download costs them the whole thing. It also makes the Windows path-length problem worse, because everything lands under an extra nested folder (see below). **Not to mention that if the entire guide is followed, only the following folders: Code/, Visualization/, Dataset/, and Curated_Data/ are used.**

> Initial Lab internal testings showed that the singular 9.5GB zip file caused major problems, so it was divided as to give the Zenodo users some flexibility.

### Why not 9.5 GB of individual files

Zenodo accepts thousands of individual files, but the browser uploader gets flaky at that count, the record page becomes unusable, and Zenodo has no "download folder" button, so users would have to click through files one at a time based on my understandings when reading the Zenodo upload guidelines.

### What this does for the user

Someone who only wants results takes `Dataset.zip` + the root files and can skip ~5 GB. Someone reproducing the analysis can take `Curated_Data.zip` + `Code.zip` + the root files. The extracted layout is identical either way, because each zip holds its folder at the top level,so the commands in `01_GETTING_STARTED.md` work for every subset. **The most important zip files to download are `Visualization` and `Dataset` as those two help inform researchers what the dataset looks like before making their plans.**

Zenodo's default limits are 50 GB per record and 5 GB per file, so 9.5 GB split this way is comfortably inside them. No quota request is needed. If I remember at the time, it was 50 GB total for the whole thing before needing to ask the admins.

---

## Before you zip: check the Windows paths

Windows cannot create a path longer than 260 characters, and Explorer's built-in extractor enforces it: extraction fails with **"Path too long"** and can leave folders **silently empty** rather than stopping. To the user that looks like a broken pipeline, not a broken download. (This is exactly what happened during internal testing.)

The 260 characters are shared between the folder the user extracts into and the path inside the archive, so a filename that is fine on macOS can be unopenable on Windows. A user extracting into `C:\Users\name\Downloads\BioSEL_Zenodo_Release\` has already spent ~50 of them before touching our files. If their unzip tool creates a nested folder of the same name, closer to 90.

```bash
uv run python Code/BioSEL-PULSE/tools/check_windows_paths.py .
```

It flags every path that will not fit, says how many characters it needs to lose, and also catches names Windows cannot create at all (illegal characters, reserved names, trailing dots or spaces).

Long **figure filenames** are the usual offender. When the containing folder already names the dataset, the file inside it does not need to repeat that name:

```
Visualization/sample_figures/BioSEL_OriginalData_Thick_100mm_ZenodoDataset_thick100_c25_run1/
    Hysteresis_&_Phase_Portrait_-_BioSEL_OriginalData_Thick_100mm_ZenodoDataset_thick100_c25_run1.png   <- 190 chars, fails
    Hysteresis_&_Phase_Portrait.png                                                                     <- 124 chars, fine
```

Also avoid `&` in filenames: it is legal, but it is a shell metacharacter, so it makes any command-line or URL reference to the file awkward to quote.

---

## Making the zips (MacOS only)

Zip so each archive holds its folder at the top level, with no wrapper folder around it:

```bash
# from the root
zip -r Dataset.zip      Dataset      -x '*.DS_Store' -x '__MACOSX*'
zip -r Curated_Data.zip Curated_Data -x '*.DS_Store' -x '__MACOSX*'
zip -r Raw_Data.zip     Raw_Data     -x '*.DS_Store' -x '__MACOSX*'
zip -r Code.zip         Code         -x '*.DS_Store' -x '__MACOSX*' -x '*__pycache__*'
zip -r Visualization.zip Visualization -x '*.DS_Store' -x '__MACOSX*' -x '*.ipynb_checkpoints*'
zip -r Hardware.zip     Hardware     -x '*.DS_Store' -x '__MACOSX*'
```

**Do not use Finder's "Compress" on macOS.** It adds `__MACOSX/` resource-fork entries and
`.DS_Store` files, which show up as junk for everyone extracting on Windows or Linux.

Do not zip `.venv/`. It is machine-specific and enormous, and `uv sync` rebuilds it in seconds
from `uv.lock`. The `-x` patterns above and the repo's `.gitignore` already keep it out, but
confirm before uploading.

The hidden `.metadata.yaml` config files inside the data folders **must** be included: they
are what reproduce the published PKL. `zip -r` includes dotfiles by default; verify with:

```bash
unzip -l Curated_Data.zip | grep -c metadata.yaml
```

---

## Verify before you publish

Do this on a **different machine** than the one that built the package, ideally a Windows
one:

1. Download `Dataset.zip` + the root files only. Confirm `uv sync` works and
   `uv run python Code/BioSEL-PULSE/explore/inspect_pkl_results.py --input Dataset` opens the PKL. (This is the most common user path, and it is the one that breaks if the environment files got zipped into `Code.zip`.)
2. Extract into a deliberately deep folder such as `C:\Users\<you>\Downloads\BioSEL_Zenodo_Release\` and confirm nothing reports "Path too long".
3. Count the CSVs after extraction and compare to the source:

   ```powershell
   (Get-ChildItem -Recurse -Filter *.csv Curated_Data).Count
   ```

   A count lower than expected means the extraction silently truncated, which is the failure mode this whole document exists to prevent.

> Author's Note: It really does show that some of the authors are primarily Linux or MacOS users. So I dont know what's the equivalent is on Windows
