# PyInstaller spec for the Linux single-file SAT-SA build.
#
# Reproducible: `bash packaging/build-linux.sh` from the repository root.
# One entry (packaging/satsa_main.py), one output file
# (dist/satsa/SAT-SA-linux). Product code is untouched; only
# backend/datasets.py (SATSA_DATA_ROOT override, bundle_root helper) and
# backend/app.py (frontend bundle location) know about frozen mode, and
# both behave exactly as before when unfrozen.

import os

# SPEC is the spec file path (packaging/satsa-linux.spec); the project
# root is its parent directory.
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
block_cipher = None

a = Analysis(
    [os.path.join(PROJECT, "packaging", "satsa_main.py")],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(PROJECT, "frontend", "dist"), "frontend/dist"),
        (os.path.join(PROJECT, "framework", "config"), "framework/config"),
        (
            os.path.join(
                PROJECT, "framework", "canonical", "canonical_schema.json"
            ),
            "framework/canonical",
        ),
        (
            os.path.join(PROJECT, "packaging", "starter-data"),
            "packaging/starter-data",
        ),
    ],
    hiddenimports=[
        # Lazily imported by the offline anomaly layer; invisible to the
        # static analysis, required at runtime when the model exists.
        "sklearn",
        "sklearn.ensemble",
        "sklearn.ensemble._iforest",
        "sklearn.tree",
        "sklearn.neighbors",
        "sklearn.utils",
        "sklearn.utils._typedefs",
        "scipy",
        "scipy.sparse",
        "joblib",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "tkinter",
        "streamlit",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "notebook",
        "IPython",
        # Dragged in by sklearn's optional array-API compat; the bundled
        # Isolation Forest never touches it. Excluded to keep the
        # single file distributable (torch + CUDA is gigabytes).
        "torch",
        "torchvision",
        "torchaudio",
        "triton",
        "tensorflow",
        "cupy",
        "jax",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SAT-SA-linux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
