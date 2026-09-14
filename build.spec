# PyInstaller spec - works on whichever OS you run it on (Windows/macOS/Linux).
# Build with: pyinstaller build.spec
#
# Produces a single-folder distribution (dist/EsignInvoices/) rather than
# --onefile: onefile re-extracts to a temp dir on every launch, which is
# slower and can trip some PKCS#11 drivers that expect a stable install
# path. On macOS this also gets wrapped into a proper .app bundle.
import sys

block_cipher = None

hiddenimports = ['pkcs11']
if sys.platform == 'win32':
    hiddenimports.append('keyring.backends.Windows')
elif sys.platform == 'darwin':
    hiddenimports.append('keyring.backends.macOS')
else:
    hiddenimports.append('keyring.backends.SecretService')

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
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

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='EsignInvoices.app',
        icon=None,
        bundle_identifier='mk.esign.invoices',
        info_plist={'NSHighResolutionCapable': True},
    )
