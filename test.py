import sys
import fitz
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QVBoxLayout,
    QScrollArea, QWidget, QComboBox, QLineEdit, QPushButton, QHBoxLayout, QMessageBox,
    QMenu, QInputDialog
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QCursor
from PyQt5.QtCore import Qt, QRect, QTimer

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

# 支持多色高亮+批注的页面控件，及鼠标高亮提示
class SelectablePDFPage(QLabel):
    def __init__(self, page, qimg, page_idx, highlight_colors, parent=None):
        super().__init__(parent)
        self.page = page
        self.base_qimg = qimg
        self.page_idx = page_idx
        self.setPixmap(QPixmap.fromImage(self.base_qimg))
        self.setAlignment(Qt.AlignCenter)
        self.selection_rect = None
        self.highlights = []  # 每项: {'rect': QRect, 'color': QColor, 'note': str}
        self.selecting = False
        self.start_pos = None
        self.end_pos = None
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.highlight_colors = highlight_colors

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
        else:
            # 悬停显示批注
            tip = ""
            for h in self.highlights:
                if h['rect'].contains(event.pos()):
                    if h['note']:
                        tip = f"{h['note']}"
                    break
            self.setToolTip(tip)
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
            color_actions = []
            for name, color in self.highlight_colors:
                act = menu.addAction(f"高亮：{name}")
                color_actions.append((act, color))
            act_cancel = menu.addAction("取消")
            action = menu.exec_(self.mapToGlobal(pos))
            if action != act_cancel and action is not None:
                # 弹窗输入批注
                note, ok = QInputDialog.getText(self, "输入批注", "为高亮内容添加批注（可选）：")
                idx = [a for a, _ in color_actions].index(action)
                color = color_actions[idx][1]
                self.highlights.append({
                    'rect': QRect(self.selection_rect),
                    'color': QColor(*color, 80),
                    'note': note if ok and note else "",
                })
                self.selection_rect = None
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, QPixmap.fromImage(self.base_qimg))
        painter.setRenderHint(QPainter.Antialiasing)
        for h in self.highlights:
            painter.fillRect(h['rect'], h['color'])
        if self.selection_rect:
            painter.setPen(QPen(Qt.red, 2, Qt.DashLine))
            painter.drawRect(self.selection_rect)
        painter.end()

    def get_selected_text(self):
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

# 懒加载连续PDF主窗口
class LazyPDFViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt 连续滚动PDF高亮+懒加载阅读器")
        self.resize(1000, 800)
        self.pdf_doc = None
        self.loaded_pages = {}   # idx: SelectablePDFPage
        self.current_mode = "默认"
        self.current_viewport_width = 0
        self.visible_range = (0, 0)
        self.max_pages_mem = 10  # 同时最多缓存的页面数（可按机器内存调大）
        self.page_height_hint = 800
        # 多色高亮
        self.highlight_colors = [
            ("黄色", (255, 255, 0)),
            ("绿色", (0, 255, 100)),
            ("蓝色",  (30, 160, 255)),
            ("粉色",  (255, 160, 255)),
            ("橙色",  (255, 180, 40)),
        ]

        widget = QWidget()
        vbox = QVBoxLayout(widget)
        top_bar = QHBoxLayout()
        open_btn = QPushButton("打开PDF")
        open_btn.clicked.connect(self.open_pdf)
        self.mode_box = QComboBox()
        self.mode_box.addItems(["默认", "夜间", "护眼"])
        self.mode_box.currentIndexChanged.connect(self.reload_pages)
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

        # 滚动懒加载
        self.scroll.verticalScrollBar().valueChanged.connect(self.on_scroll)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.check_visible_pages)

    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        self.pdf_doc = fitz.open(path)
        self.page_info.setText(f"共 {self.pdf_doc.page_count} 页")
        self.loaded_pages.clear()
        for i in reversed(range(self.inner_layout.count())):
            widget = self.inner_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        # 预估每页高度
        first_page = self.pdf_doc.load_page(0)
        zoom = self.get_dynamic_zoom()
        mat = fitz.Matrix(zoom, zoom)
        pix = first_page.get_pixmap(matrix=mat, alpha=False)
        self.page_height_hint = pix.height + 16
        # 填充布局占位
        for i in range(self.pdf_doc.page_count):
            ph = QLabel()
            ph.setMinimumHeight(self.page_height_hint)
            self.inner_layout.addWidget(ph)
        self.reload_pages()
        QTimer.singleShot(100, self.check_visible_pages)

    def get_dynamic_zoom(self):
        if not self.pdf_doc:
            return 1.0
        view_w = self.scroll.viewport().width()
        pdf_w = self.pdf_doc.load_page(0).rect.width
        if pdf_w == 0:
            return 1.0
        zoom = view_w / pdf_w * 0.98
        return zoom

    def reload_pages(self):
        self.loaded_pages.clear()
        self.check_visible_pages()

    def on_scroll(self):
        # 滚动时避免频繁重渲染，做延迟
        self.scroll_timer.start(50)

    def check_visible_pages(self):
        if not self.pdf_doc:
            return
        bar = self.scroll.verticalScrollBar()
        y0 = bar.value()
        y1 = y0 + self.scroll.viewport().height()
        # 估算当前可见页idx范围
        p_start = max(int(y0 // self.page_height_hint) - 2, 0)
        p_end = min(int(y1 // self.page_height_hint) + 2, self.pdf_doc.page_count - 1)
        # 加载/销毁
        for i in range(self.pdf_doc.page_count):
            item = self.inner_layout.itemAt(i)
            if p_start <= i <= p_end:
                if i not in self.loaded_pages:
                    self.load_page(i)
            else:
                if i in self.loaded_pages:
                    w = self.loaded_pages.pop(i)
                    w.setParent(None)
                    ph = QLabel()
                    ph.setMinimumHeight(self.page_height_hint)
                    self.inner_layout.insertWidget(i, ph)
        # 控制最大页面缓存
        while len(self.loaded_pages) > self.max_pages_mem:
            farthest = max(self.loaded_pages, key=lambda idx: abs((p_start+p_end)//2-idx))
            w = self.loaded_pages.pop(farthest)
            w.setParent(None)
            ph = QLabel()
            ph.setMinimumHeight(self.page_height_hint)
            self.inner_layout.insertWidget(farthest, ph)

    def load_page(self, idx):
        page = self.pdf_doc.load_page(idx)
        mode = self.mode_box.currentText()
        zoom = self.get_dynamic_zoom()
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        if mode == "夜间":
            qimg = fitz_pix_to_qimage(pix, "night")
        elif mode == "护眼":
            qimg = fitz_pix_to_qimage(pix, "eye")
        else:
            qimg = fitz_pix_to_qimage(pix, "default")
        label = SelectablePDFPage(page, qimg, idx, self.highlight_colors)
        label.setMinimumHeight(self.page_height_hint)
        self.inner_layout.insertWidget(idx, label)
        ph = self.inner_layout.itemAt(idx+1).widget()
        if isinstance(ph, QLabel) and ph is not label:
            ph.setParent(None)
        self.loaded_pages[idx] = label

    def jump_page(self):
        if not self.pdf_doc:
            return
        try:
            p = int(self.page_edit.text()) - 1
            if not (0 <= p < self.pdf_doc.page_count):
                QMessageBox.warning(self, "提示", "页码超出范围")
                return
            label = self.loaded_pages.get(p)
            if not label:
                self.load_page(p)
                label = self.loaded_pages[p]
            self.scroll.ensureWidgetVisible(label)
        except:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_width = self.scroll.viewport().width()
        if new_width != self.current_viewport_width:
            self.current_viewport_width = new_width
            self.reload_pages()

    def copy_selected_text(self):
        for label in self.loaded_pages.values():
            text = label.get_selected_text()
            if text:
                QApplication.clipboard().setText(text)
                QMessageBox.information(self, "已复制", "所选文字已复制到剪贴板！")
                return
        QMessageBox.warning(self, "无选区", "未选择任何文字区域！")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = LazyPDFViewer()
    viewer.show()
    sys.exit(app.exec_())
