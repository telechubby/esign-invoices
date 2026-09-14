# PyInstaller spec for the Windows build.
# Build on Windows with: pyinstaller build.spec
#
# Produces a single-folder distribution (dist/EsignInvoices/) rather than
# --onefile: onefile re-extracts to a temp dir on every launch, which is
# slower and can trip some PKCS#11 drivers that expect a stable install
# path. A folder is also easier to debug on-site.

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['pkcs11', 'keyring.backends.Windows'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EsignInvoices',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='EsignInvoices',
)
