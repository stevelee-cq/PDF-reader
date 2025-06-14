import sys
import fitz  # PyMuPDF
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QVBoxLayout,
    QScrollArea, QWidget, QComboBox, QLineEdit, QPushButton, QHBoxLayout, QMessageBox
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
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img = img[..., :3]  # Ignore alpha for mode processing
    if mode == "night":
        img = invert_rgb(img)
    elif mode == "eye":
        img = eye_care_rgb(img)
    qimg = QImage(img.data, pix.width, pix.height, pix.width*3, QImage.Format_RGB888)
    return qimg.copy()  # 必须copy

class ContinuousPDFViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt 连续滚动PDF阅读器")
        self.resize(1000, 800)
        self.pdf_doc = None
        self.page_imgs = []
        self.current_mode = "default"
        self.current_viewport_width = 0  # 跟踪窗口内容区宽度

        widget = QWidget()
        vbox = QVBoxLayout(widget)
        top_bar = QHBoxLayout()
        open_btn = QPushButton("打开PDF")
        open_btn.clicked.connect(self.open_pdf)
        self.mode_box = QComboBox()
        self.mode_box.addItems(["默认", "夜间", "护眼"])
        self.mode_box.currentIndexChanged.connect(self.update_pages)
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("跳转页码")
        self.jump_btn = QPushButton("跳转")
        self.jump_btn.clicked.connect(self.jump_page)
        self.page_info = QLabel("")
        top_bar.addWidget(open_btn)
        top_bar.addWidget(self.mode_box)
        top_bar.addWidget(self.page_edit)
        top_bar.addWidget(self.jump_btn)
        top_bar.addWidget(self.page_info)
        top_bar.addStretch()
        vbox.addLayout(top_bar)

        # 滚动显示所有页面
        self.scroll = QScrollArea(self)
        self.inner_widget = QWidget()
        self.inner_layout = QVBoxLayout(self.inner_widget)
        self.inner_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.inner_widget)
        self.scroll.setWidgetResizable(True)
        vbox.addWidget(self.scroll)
        self.setCentralWidget(widget)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        self.pdf_doc = fitz.open(path)
        self.page_info.setText(f"共 {self.pdf_doc.page_count} 页")
        self.update_pages()

    def get_dynamic_zoom(self):
        """返回让PDF横向铺满可视区的动态缩放因子。"""
        if not self.pdf_doc:
            return 1.0
        # 只取第一页宽度作为参考（一般每页都一样）
        view_w = self.scroll.viewport().width()
        pdf_w = self.pdf_doc.load_page(0).rect.width
        if pdf_w == 0:
            return 1.0
        # 留一点点边距，乘0.98
        zoom = view_w / pdf_w * 0.98
        return zoom

    def update_pages(self):
        # 清理之前的
        for i in reversed(range(self.inner_layout.count())):
            widget = self.inner_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        self.page_imgs = []
        if not self.pdf_doc:
            return
        mode = self.mode_box.currentText()
        zoom = self.get_dynamic_zoom()
        for i, page in enumerate(self.pdf_doc):
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            if mode == "夜间":
                qimg = fitz_pix_to_qimage(pix, "night")
            elif mode == "护眼":
                qimg = fitz_pix_to_qimage(pix, "eye")
            else:
                qimg = fitz_pix_to_qimage(pix, "default")
            label = QLabel()
            label.setPixmap(QPixmap.fromImage(qimg))
            label.setAlignment(Qt.AlignCenter)
            self.inner_layout.addWidget(label)
            self.page_imgs.append(label)
        self.page_info.setText(f"共 {self.pdf_doc.page_count} 页")

    def jump_page(self):
        if not self.pdf_doc:
            return
        try:
            p = int(self.page_edit.text()) - 1
            if not (0 <= p < self.pdf_doc.page_count):
                QMessageBox.warning(self, "提示", "页码超出范围")
                return
            label = self.page_imgs[p]
            self.scroll.ensureWidgetVisible(label)
        except:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 判断宽度有变，才重渲染，避免死循环
        new_width = self.scroll.viewport().width()
        if new_width != self.current_viewport_width:
            self.current_viewport_width = new_width
            self.update_pages()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = ContinuousPDFViewer()
    viewer.show()
    sys.exit(app.exec_())
