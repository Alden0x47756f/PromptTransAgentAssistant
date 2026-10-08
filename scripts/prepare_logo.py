"""Prepare runtime PNG and a multi-resolution Windows icon from the approved logo."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

root = Path(__file__).resolve().parents[1]
source = QImage(str(root / 'assets' / 'branding' / 'logo-v2.png'))
if source.isNull() or not source.hasAlphaChannel():
    raise ValueError('Approved logo must be a readable transparent PNG.')
source = source.convertToFormat(QImage.Format.Format_RGBA8888)
pixels = bytes(source.constBits())
left, top, right, bottom = source.width(), source.height(), -1, -1
for y in range(source.height()):
    row = pixels[y * source.bytesPerLine():y * source.bytesPerLine() + source.width() * 4]
    occupied = [x for x, alpha in enumerate(row[3::4]) if alpha > 16]
    if occupied:
        left, right = min(left, occupied[0]), max(right, occupied[-1])
        top, bottom = min(top, y), max(bottom, y)
if right < left:
    raise ValueError('Approved logo is empty.')
source = source.copy(left, top, right - left + 1, bottom - top + 1)
mark = source.scaled(410, 410, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
logo = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
logo.fill(Qt.GlobalColor.transparent)
painter = QPainter(logo)
painter.drawImage((512 - mark.width()) // 2, (512 - mark.height()) // 2, mark)
painter.end()
destination = root / 'frontend' / 'branding'
destination.mkdir(exist_ok=True)
if not logo.save(str(destination / 'logo.png')):
    raise OSError('Could not save runtime logo.')

# A white rounded tile keeps the dark mark visible on any desktop background.
tile = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
tile.fill(Qt.GlobalColor.transparent)
painter = QPainter(tile)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#ffffff'))
painter.drawRoundedRect(QRectF(8, 8, 496, 496), 108, 108)
painter.drawImage(0, 0, logo)
painter.end()

sizes = (16, 24, 32, 48, 64, 128, 256)
images = []
for size in sizes:
    image = tile.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError(f'Could not encode {size}px icon.')
    images.append(bytes(data))
offset = 6 + 16 * len(images)
entries = []
for size, data in zip(sizes, images):
    entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                               1, 32, len(data), offset))
    offset += len(data)
(destination / 'app.ico').write_bytes(struct.pack('<HHH', 0, 1, len(images))
                                     + b''.join(entries) + b''.join(images))
print('Prepared logo.png and app.ico (16/24/32/48/64/128/256px).')
