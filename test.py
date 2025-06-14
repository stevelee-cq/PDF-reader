import sys
import fitz
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QVBoxLayout,
    QScrollArea, QWidget, QComboBox, QLineEdit, QPushButton, QHBoxLayout, QMessageBox,
    QMenu
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QRect

# -------- 图像模式处理函数 --------
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
        img = img[..., :3]  # 忽略alpha
    if mode == "night":
        img = invert_rgb(img)
    elif mode == "eye":
        img = eye_care_rgb(img)
    qimg = QImage(img.data, pix.width, pix.height, pix.width*3, QImage.Format_RGB888)
    return qimg.copy()  # 必须copy

# -------- 支持鼠标选区和高亮的页面控件 --------
class SelectablePDFPage(QLabel):
    def __init__(self, page, qimg, parent=None):
        super().__init__(parent)
        self.page = page            # PyMuPDF page对象
        self.base_qimg = qimg       # 当前显示的QImage（已模式变换）
        self.setPixmap(QPixmap.fromImage(self.base_qimg))
        self.setAlignment(Qt.AlignCenter)
        self.selection_rect = None  # 当前选区
        self.highlights = []        # [QRect, ...]，每个为高亮区域
        self.selecting = False
        self.start_pos = None
        self.end_pos = None
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selecting = True
            self.start_pos = event.pos()
            self.end_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, self.end_pos)
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.selecting:
            self.end_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selecting:
            self.end_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            self.selecting = False
            self.update()
        super().mouseReleaseEvent(event)

    def context_menu(self, pos):
        if self.selection_rect and self.selection_rect.width() > 5 and self.selection_rect.height() > 5:
            menu = QMenu(self)
            act_highlight = menu.addAction("高亮所选内容")
            action = menu.exec_(self.mapToGlobal(pos))
            if action == act_highlight:
                self.highlights.append(self.selection_rect)
                self.selection_rect = None
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, QPixmap.fromImage(self.base_qimg))
        painter.setRenderHint(QPainter.Antialiasing)
        # 所有高亮
        for rect in self.highlights:
            painter.fillRect(rect, QColor(255, 255, 0, 80))  # 半透明黄
        # 当前选区
        if self.selection_rect:
            painter.setPen(QPen(Qt.red, 2, Qt.DashLine))
            painter.drawRect(self.selection_rect)
        painter.end()

    def get_selected_text(self):
        """返回当前选区内的PDF文本（用像素选区映射到PDF坐标）。"""
        if not self.selection_rect or self.selection_rect.width() < 5 or self.selection_rect.height() < 5:
            return ""
        qimg_w, qimg_h = self.base_qimg.width(), self.base_qimg.height()
        page_rect = self.page.rect
        scale_x = page_rect.width / qimg_w
        scale_y = page_rect.height / qimg_h
        x1 = self.selection_rect.left() * scale_x
        y1 = self.selection_rect.top() * scale_y
        x2 = self.selection_rect.right() * scale_x
        y2 = self.selection_rect.bottom() * scale_y
        select_box = fitz.Rect(x1, y1, x2, y2)
        words = self.page.get_text("words")
        selected_words = [w[4] for w in words if fitz.Rect(w[:4]).intersects(select_box)]
        return " ".join(selected_words)

# -------- 主窗口 --------
class ContinuousPDFViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt 连续滚动PDF高亮阅读器")
        self.resize(1000, 800)
        self.pdf_doc = None
        self.page_imgs = []
        self.current_mode = "default"
        self.current_viewport_width = 0

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
        self.copy_btn = QPushButton("复制所选文字")
        self.copy_btn.clicked.connect(self.copy_selected_text)
        top_bar.addWidget(open_btn)
        top_bar.addWidget(self.mode_box)
        top_bar.addWidget(self.page_edit)
        top_bar.addWidget(self.jump_btn)
        top_bar.addWidget(self.copy_btn)
        top_bar.addWidget(self.page_info)
        top_bar.addStretch()
        vbox.addLayout(top_bar)

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
        if not self.pdf_doc:
            return 1.0
        view_w = self.scroll.viewport().width()
        pdf_w = self.pdf_doc.load_page(0).rect.width
        if pdf_w == 0:
            return 1.0
        zoom = view_w / pdf_w * 0.98
        return zoom

    def update_pages(self):
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
            label = SelectablePDFPage(page, qimg)
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
        new_width = self.scroll.viewport().width()
        if new_width != self.current_viewport_width:
            self.current_viewport_width = new_width
            self.update_pages()

    def copy_selected_text(self):
        for label in self.page_imgs:
            text = label.get_selected_text()
            if text:
                QApplication.clipboard().setText(text)
                QMessageBox.information(self, "已复制", "所选文字已复制到剪贴板！")
                return
        QMessageBox.warning(self, "无选区", "未选择任何文字区域！")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = ContinuousPDFViewer()
    viewer.show()
    sys.exit(app.exec_())
