# Third-party notices

The application's MIT license does not replace third-party licenses. Windows
release packages include copies of applicable license texts in
`third-party-licenses/`.

- Python 3.11: Python Software Foundation license; [source](https://github.com/python/cpython/tree/3.11).
- PySide6 / Shiboken and Qt: the distributed open-source components are subject
  to their respective LGPL / GPL and third-party terms. See
  [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html),
  [PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/), and
  [Qt source repositories](https://code.qt.io/cgit/qt/).
- Qt WebEngine includes Chromium and other third-party components; see
  [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html).
- HTTPX, HTTP Core, h11, AnyIO, idna, typing_extensions and certifi: see the
  included license files and the upstream package distributions.
- PyInstaller's bootloader is distributed under its license and exception;
  the complete license is included in `third-party-licenses/PyInstaller.txt`.

The public source repository and build scripts permit rebuilding this
application with separately installed dependencies. No model weights or
llama engine binaries are included; users obtain them separately under their
own licenses. The approved logo was generated with an image-generation tool.
