# Developer Guide - Building MyDashApp Distribution

## Quick Start for Developers

This guide walks you through creating a distributable Windows installer for your Dash app.

## Step-by-Step Build Process

### 1. Download Embedded Python

```
1. Visit: https://www.python.org/downloads/windows/
2. Find Python 3.12.x
3. Download: "Windows embeddable package (64-bit)"
4. Extract ALL files to: MyDashApp\python\
```

**Important:** The python folder should contain:
- python.exe
- python312.dll
- python312._pth
- All other Python files

### 2. Enable pip in Embedded Python

Open `python\python312._pth` and edit:

**Before:**
```
python312.zip
.
#import site
```

**After:**
```
python312.zip
.
import site
```

(Just remove the # from the last line)

### 3. Install Python Dependencies

Open Command Prompt in the MyDashApp folder and run:

```cmd
python\python.exe -m ensurepip
python\python.exe -m pip install --upgrade pip
python\python.exe -m pip install -r requirements.txt
```

This will take a few minutes to download and install Dash, Plotly, and Pandas.

### 4. Test Locally

Test that everything works before building the installer:

```cmd
run_app.bat
```

- A browser window should open automatically
- You should see your Dash app running
- Press Ctrl+C in the command window to stop

### 5. Install NSIS

Download and install NSIS (Nullsoft Scriptable Install System):
```
https://nsis.sourceforge.io/Download
```

Install it with default options.

### 6. Build the Installer

**Method 1: Right-click**
1. Right-click on `build_installer.nsi`
2. Select "Compile NSIS Script"

**Method 2: Command Line**
```cmd
"C:\Program Files (x86)\NSIS\makensis.exe" build_installer.nsi
```

This creates: `MyDashAppInstaller.exe`

### 7. Test the Installer

1. Copy `MyDashAppInstaller.exe` to a test location
2. Run it
3. Follow installation prompts
4. Test the installed app from the desktop shortcut

### 8. Distribute

Share `MyDashAppInstaller.exe` with users!

## File Structure Explained

```
MyDashApp/
├── python/                    # Embedded Python (you download this)
│   ├── python.exe
│   ├── python312.dll
│   ├── python312._pth        # EDIT THIS to enable pip!
│   └── ...
├── app/
│   ├── app.py                # Your main Dash app
│   ├── components/
│   │   └── layout.py         # Reusable components
│   └── assets/               # Auto-loaded by Dash
│       ├── styles.css        # CSS styling
│       └── script.js         # JavaScript
├── requirements.txt          # Python packages needed
├── setup.bat                 # Installs dependencies
├── run_app.bat              # Launches the app
├── build_installer.nsi      # NSIS installer script
└── README.md                # User documentation
```

## Customizing Your App

### Change App Name/Version

Edit `build_installer.nsi`:
```nsis
!define APPNAME "MyDashApp"      # Change this
!define VERSION "1.0"            # Change this
!define COMPANY "MyCompany"      # Change this
```

### Add More Python Packages

Edit `requirements.txt`:
```
dash==2.18.1
pandas==2.2.3
plotly==5.24.1
numpy==1.26.0        # Add new packages here
```

Then reinstall dependencies (step 3) and rebuild installer (step 6).

### Modify the UI

- **Layout**: Edit `app/components/layout.py`
- **Styling**: Edit `app/assets/styles.css`
- **JavaScript**: Edit `app/assets/script.js`
- **Main Logic**: Edit `app/app.py`

## Optional Performance Benchmarks

Install the development dependencies and run the opt-in benchmarks from the repository root:

```cmd
python -m pip install -r requirements-dev.txt
python -m playwright install
python -m pytest benchmarks\benchmark_sea_anemone.py --benchmark-only --benchmark-columns=mean,median,stddev
```

The suite measures USF archive loading, saved-session restoration, server-side Plotly figure rendering and JSON serialization, single-site inversion, and full inversion using the included 74-site sample archive. It is kept outside `tests/` so the benchmarks do not run as part of the regular CI test suite. Results are machine-dependent; compare runs on the same machine and dataset.

To run the original single-site end-to-end benchmark:

```cmd
python -m playwright install chromium
python -m pytest benchmarks\benchmark_playwright_selection.py --benchmark-only --benchmark-columns=mean,median,stddev
```

For a separate comparison of one site against multiple sites, run:

```cmd
python -m pytest benchmarks\benchmark_playwright_selection_sizes.py --benchmark-only --benchmark-columns=mean,median,stddev
```

Both files start an isolated app server with the included sample archive loaded and simulate map selections in Chromium. The original benchmark covers a single-site update. The comparison benchmark measures 1, 10, 25, and all available sites, making the one-site case a direct baseline for the multi-site cases. Each case verifies the linked plots and repeats the measurement ten times. Results are machine-dependent, so compare runs on the same machine.

To benchmark loading the archive from the app's initial Upload screen through the map and plots becoming usable, run:

```cmd
python -m pytest benchmarks\benchmark_playwright_load_data.py --benchmark-only --benchmark-columns=mean,median,stddev
```

This benchmark selects the included archive through the browser file input using Chromium's ZIP MIME type, switches to Process, verifies that the map contains all expected sites and the sounding, apparent-resistivity, and section plots contain their expected data, and reports median and maximum latency. It repeats the workflow three times; app/page reset is outside the reported browser-visible latency. To benchmark a different ZIP, set `PLAYWRIGHT_UPLOAD_ARCHIVE` to its path before running pytest.

To benchmark switching between Process, Invert, QC, and Interpret and verify the resulting views are interactive, run:

```cmd
python -m pytest benchmarks\benchmark_playwright_view_switch.py --benchmark-only --benchmark-columns=mean,median,stddev
```

The test repeats the Invert → QC → Interpret → Process sequence three times. For each switch it waits for the expected plots to be visible and rendered, verifies Plotly has the map in non-static interactive mode, then records click-to-usable-view latency.

To benchmark the real all-sites inversion's first progress update and completed results separately, run:

```cmd
python -m pytest benchmarks\benchmark_playwright_inversion_feedback.py --benchmark-only --benchmark-columns=mean,median,stddev
```

This benchmark uses the included sample archive and repeats each measurement twice, resetting the session between runs. Click-to-first-progress measures when the elapsed-time display first changes from `0:00`
Click-to-results measures when the inversion button is re-enabled and the results plot displays “Inversion Finished.” 

## Browser Smoke Test

Install the development dependencies and Chromium once:

```cmd
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Start the app with `run_app.bat` or '.\.venv\Scripts\python.exe .\app\app.py', then run the browser test from another terminal:

```cmd
 .\.venv\Scripts\Activate.ps1
python -m pytest tests\test_playwright_smoke.py -q
```

The test uses `http://127.0.0.1:8050` by default. Set `PLAYWRIGHT_BASE_URL` to test a different running instance.

## Common Issues

### "pip not found"
- Make sure you edited `python312._pth` correctly
- Check that `import site` is uncommented (no # symbol)

### "Module not found" error when running
- Run the dependency installation again (step 3)
- Make sure all packages installed successfully

### Installer creates shortcuts but app won't run
- Test with `run_app.bat` first
- Check that `setup.bat` ran successfully during installation
- Make sure port 8050 is not in use

### Large installer size
- This is normal! Embedded Python + packages = ~150-250 MB
- You can use UPX to compress the executable

## Advanced: Updating the App

When you make changes:

1. Edit your app files
2. Test with `run_app.bat`
3. Update version in `build_installer.nsi`
4. Rebuild installer (step 6)
5. Distribute new installer

Users can install over the old version or uninstall first.

## Distribution Checklist

- [ ] Python embedded downloaded and extracted
- [ ] python312._pth modified to enable pip
- [ ] Dependencies installed locally
- [ ] App tested with run_app.bat
- [ ] NSIS installed
- [ ] Installer built successfully
- [ ] Installer tested on clean machine
- [ ] README.md updated for users
- [ ] Version number updated

## Tips

1. **Test on a clean Windows VM** - Best way to ensure it works for users
2. **Include version in filename** - E.g., `MyDashApp_v1.0_Installer.exe`
3. **Sign your installer** - For production, get a code signing certificate
4. **Compress with UPX** - Reduces installer size (optional)
5. **Auto-update mechanism** - Consider adding for future versions

## Support

Need help? Check:
- Dash documentation: https://dash.plotly.com/
- NSIS documentation: https://nsis.sourceforge.io/Docs/

Happy distributing! 🚀
