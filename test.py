#这是pyqt5的代码
import sys
import fitz  # PyMuPDF
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QVBoxLayout,
    QScrollArea, QWidget, QComboBox, QLineEdit, QPushButton, QHBoxLayout
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt

def invert_rgb(arr):
    return 255 - arr

def eye_care_rgb(arr):
    arr = arr.astype(np.float32)
    arr[..., 0] *= 0.9   # R
    arr[..., 1] *= 1.13  # G
    arr[..., 2] *= 0.92  # B
    arr = np.clip(arr, 0, 255)
    return arr.astype(np.uint8)

def fitz_pix_to_qimage(pix, mode="default"):
    # Always to RGB np.array
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img = img[..., :3]  # Ignore alpha for mode processing

    if mode == "night":
        img = invert_rgb(img)
    elif mode == "eye":
        img = eye_care_rgb(img)
    # QImage需要bytes/strides
    qimg = QImage(img.data, pix.width, pix.height, pix.width*3, QImage.Format_RGB888)
    return qimg.copy()  # 必须copy，否则可能闪退

class PDFViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt PDF阅读器")
        self.resize(1000, 800)
        self.pdf_doc = None
        self.pages_pixmaps = []
        self.page_imgs = []
        self.current_mode = "default"
        self.current_page = 0

        # ===== 控件布局 =====
        self.scroll = QScrollArea(self)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.label)
        self.scroll.setWidgetResizable(True)

        widget = QWidget()
        vbox = QVBoxLayout(widget)
        # 上栏
        top_bar = QHBoxLayout()
        open_btn = QPushButton("打开PDF")
        open_btn.clicked.connect(self.open_pdf)
        self.mode_box = QComboBox()
        self.mode_box.addItems(["默认", "夜间", "护眼"])
        self.mode_box.currentIndexChanged.connect(self.change_mode)
        top_bar.addWidget(open_btn)
        top_bar.addWidget(self.mode_box)
        # 页码跳转
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("页码")
        self.jump_btn = QPushButton("跳转")
        self.jump_btn.clicked.connect(self.jump_page)
        self.page_info = QLabel("")
        top_bar.addWidget(self.page_edit)
        top_bar.addWidget(self.jump_btn)
        top_bar.addWidget(self.page_info)
        top_bar.addStretch()
        vbox.addLayout(top_bar)
        vbox.addWidget(self.scroll)
        self.setCentralWidget(widget)

        # 滚轮切页
        self.scroll.viewport().installEventFilter(self)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        self.pdf_doc = fitz.open(path)
        self.current_page = 0
        self.page_info.setText(f"共 {self.pdf_doc.page_count} 页")
        self.render_page()

    def render_page(self):
        if not self.pdf_doc:
            return
        page = self.pdf_doc.load_page(self.current_page)
        # 用当前窗口宽度适配
        view_w = self.scroll.viewport().width()
        zoom = view_w / page.rect.width if page.rect.width > 0 else 1.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        mode = self.mode_box.currentText()
        if mode == "夜间":
            qimg = fitz_pix_to_qimage(pix, "night")
        elif mode == "护眼":
            qimg = fitz_pix_to_qimage(pix, "eye")
        else:
            qimg = fitz_pix_to_qimage(pix, "default")
        self.label.setPixmap(QPixmap.fromImage(qimg))
        self.page_info.setText(f"第 {self.current_page+1} / {self.pdf_doc.page_count} 页")

    def change_mode(self):
        self.render_page()

    def jump_page(self):
        if not self.pdf_doc:
            return
        try:
            p = int(self.page_edit.text()) - 1
            if not (0 <= p < self.pdf_doc.page_count):
                return
            self.current_page = p
            self.render_page()
        except:
            pass

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == 31:  # Wheel event
            if not self.pdf_doc:
                return False
            if event.angleDelta().y() > 0 and self.current_page > 0:
                self.current_page -= 1
                self.render_page()
                return True
            elif event.angleDelta().y() < 0 and self.current_page < self.pdf_doc.page_count - 1:
                self.current_page += 1
                self.render_page()
                return True
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_page()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = PDFViewer()
    viewer.show()
    sys.exit(app.exec_())
