import sys
import fitz
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QVBoxLayout,
    QScrollArea, QWidget, QComboBox, QLineEdit, QPushButton, QHBoxLayout, QMessageBox,
    QMenu, QInputDialog
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QRect, QTimer

# -------- 图像模式处理函数 --------
def invert_rgb(arr):
    return 255 - arr

def eye_care_rgb(arr):
    arr = arr.astype(np.float32)
    arr[..., 0] *= 0.9
    arr[..., 1] *= 1.13
    arr[..., 2] *= 0.92
    arr = np.clip(arr, 0, 255)
    return arr.astype(np.uint8)

def fitz_pix_to_qimage(pix, mode="default"):
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img = img[..., :3]
    if mode == "night":
        img = invert_rgb(img)
    elif mode == "eye":
        img = eye_care_rgb(img)
    qimg = QImage(img.data, pix.width, pix.height, pix.width*3, QImage.Format_RGB888)
    return qimg.copy()

# ---- 支持文字级高亮+批注的页面控件 ----
class WordHighlightPDFPage(QLabel):
    def __init__(self, page, qimg, page_idx, highlight_colors, main_win, highlight_data=None, parent=None):
        super().__init__(parent)
        self.page = page
        self.base_qimg = qimg
        self.page_idx = page_idx
        self.setPixmap(QPixmap.fromImage(self.base_qimg))
        self.setAlignment(Qt.AlignCenter)
        self.selection_rect = None
        self.selecting = False
        self.start_pos = None
        self.end_pos = None
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)
        self.highlight_colors = highlight_colors
        self.words = page.get_text("words")
        self.highlights = highlight_data if highlight_data is not None else []
        self.main_win = main_win  # 引用主窗口

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
            tip = ""
            for h in self.highlights:
                if self.is_pos_in_words(event.pos(), h['words']):
                    if h.get('note'):
                        tip = f"批注：{h['note']}"
                        break
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selecting:
            self.end_pos = event.pos()
            self.selection_rect = QRect(self.start_pos, self.end_pos).normalized()
            self.add_default_highlight()
            self.selecting = False
            self.selection_rect = None
            self.update()
        super().mouseReleaseEvent(event)

    def add_default_highlight(self):
        sel_words = self.get_selected_words()
        if sel_words:
            color = self.highlight_colors[0][1]
            self.highlights.append({
                'words': sel_words,
                'color': QColor(*color, 80),
                'note': "",
            })

    def is_pos_in_words(self, pos, words):
        qimg_w, qimg_h = self.base_qimg.width(), self.base_qimg.height()
        page_rect = self.page.rect
        scale_x = qimg_w / page_rect.width
        scale_y = qimg_h / page_rect.height
        for w in words:
            x0, y0, x1, y1 = w[:4]
            rx0 = int(x0 * scale_x)
            ry0 = int(y0 * scale_y)
            rx1 = int(x1 * scale_x)
            ry1 = int(y1 * scale_y)
            if QRect(rx0, ry0, rx1 - rx0, ry1 - ry0).contains(pos):
                return True
        return False

    def context_menu(self, pos):
        # 仅在已有高亮上右键弹菜单
        for idx, h in enumerate(self.highlights):
            if self.is_pos_in_words(pos, h['words']):
                menu = QMenu(self)
                color_actions = []
                for name, color in self.highlight_colors:
                    act = menu.addAction(f"更改为：{name}")
                    color_actions.append((act, color))
                act_note = menu.addAction("编辑批注")
                act_del = menu.addAction("删除高亮")
                act_cancel = menu.addAction("取消")
                action = menu.exec_(self.mapToGlobal(pos))
                if action == act_del:
                    self.highlights.pop(idx)
                elif action == act_note:
                    note, ok = QInputDialog.getText(self, "编辑批注", "输入批注内容：", text=h.get("note", ""))
                    if ok:
                        self.highlights[idx]['note'] = note
                elif action in [a for a, c in color_actions]:
                    sel_idx = [a for a, c in color_actions].index(action)
                    color = color_actions[sel_idx][1]
                    self.highlights[idx]['color'] = QColor(*color, 80)
                self.update()
                return
        # 不在高亮区域右键无操作
        return

    def get_selected_words(self):
        if not self.selection_rect or self.selection_rect.width() < 5 or self.selection_rect.height() < 5:
            return []
        qimg_w, qimg_h = self.base_qimg.width(), self.base_qimg.height()
        page_rect = self.page.rect
        scale_x = page_rect.width / qimg_w
        scale_y = page_rect.height / qimg_h
        x1 = self.selection_rect.left() * scale_x
        y1 = self.selection_rect.top() * scale_y
        x2 = self.selection_rect.right() * scale_x
        y2 = self.selection_rect.bottom() * scale_y
        select_box = fitz.Rect(x1, y1, x2, y2)
        sel_words = [w for w in self.words if fitz.Rect(w[:4]).intersects(select_box)]
        return sel_words

    def get_selected_text(self):
        sel_words = self.get_selected_words()
        return " ".join(w[4] for w in sel_words)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, QPixmap.fromImage(self.base_qimg))
        painter.setRenderHint(QPainter.Antialiasing)
        qimg_w, qimg_h = self.base_qimg.width(), self.base_qimg.height()
        page_rect = self.page.rect
        scale_x = qimg_w / page_rect.width
        scale_y = qimg_h / page_rect.height
        for h in self.highlights:
            color = h['color']
            for w in h['words']:
                x0, y0, x1, y1 = w[:4]
                rx0 = int(x0 * scale_x)
                ry0 = int(y0 * scale_y)
                rx1 = int(x1 * scale_x)
                ry1 = int(y1 * scale_y)
                rect = QRect(rx0, ry0, rx1 - rx0, ry1 - ry0)
                painter.fillRect(rect, color)
        if self.selection_rect:
            painter.setPen(QPen(Qt.red, 2, Qt.DashLine))
            painter.drawRect(self.selection_rect)
        painter.end()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            main_win = self.main_win
            if hasattr(main_win, "user_zoom"):
                mouse_pos = event.pos()
                old_zoom = main_win.user_zoom
                if event.angleDelta().y() > 0 and main_win.user_zoom < 5.0:
                    main_win.user_zoom *= 1.15
                elif event.angleDelta().y() < 0 and main_win.user_zoom > 0.25:
                    main_win.user_zoom /= 1.15
                main_win.user_zoom = max(0.25, min(5.0, main_win.user_zoom))
                main_win.update_pages_and_keep_mouse_focus(self.page_idx, mouse_pos, old_zoom)
                event.accept()
                return
        super().wheelEvent(event)

# ---- 懒加载连续PDF主窗口 ----
class LazyPDFViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt 宽度优先PDF阅读器（高亮+自适应缩放+中央居中）")
        self.resize(1000, 800)
        self.pdf_doc = None
        self.loaded_pages = {}
        self.current_mode = "默认"
        self.current_viewport_width = 0
        self.max_pages_mem = 10
        self.page_height_hint = 800
        self.highlight_colors = [
            ("黄色", (255, 255, 0)),
            ("绿色", (0, 255, 100)),
            ("蓝色",  (30, 160, 255)),
            ("粉色",  (255, 160, 255)),
            ("橙色",  (255, 180, 40)),
        ]
        self.highlight_data_dict = {}
        self.user_zoom = 1.0  # 用户缩放倍数

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
        self.highlight_data_dict.clear()
        for i in reversed(range(self.inner_layout.count())):
            widget = self.inner_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        first_page = self.pdf_doc.load_page(0)
        zoom = self.get_dynamic_zoom()
        mat = fitz.Matrix(zoom, zoom)
        pix = first_page.get_pixmap(matrix=mat, alpha=False)
        self.page_height_hint = pix.height + 16
        for i in range(self.pdf_doc.page_count):
            ph = QWidget()
            hbox = QHBoxLayout(ph)
            hbox.setContentsMargins(0,0,0,0)
            hbox.addStretch()
            self.inner_layout.addWidget(ph)
        self.reload_pages()
        QTimer.singleShot(100, self.check_visible_pages)

    # 横向铺满
    def get_dynamic_zoom(self):
        if not self.pdf_doc:
            return 1.0
        view_w = self.scroll.viewport().width()
        pdf_w = self.pdf_doc.load_page(0).rect.width
        if pdf_w == 0:
            return self.user_zoom
        zoom = view_w / pdf_w * 0.98
        return zoom * self.user_zoom

    def reload_pages(self):
        self.loaded_pages.clear()
        for i in reversed(range(self.inner_layout.count())):
            widget = self.inner_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        for i in range(self.pdf_doc.page_count if self.pdf_doc else 0):
            ph = QWidget()
            hbox = QHBoxLayout(ph)
            hbox.setContentsMargins(0,0,0,0)
            hbox.addStretch()
            self.inner_layout.addWidget(ph)
        self.check_visible_pages()

    def on_scroll(self):
        self.scroll_timer.start(50)

    def check_visible_pages(self):
        if not self.pdf_doc:
            return
        bar = self.scroll.verticalScrollBar()
        y0 = bar.value()
        y1 = y0 + self.scroll.viewport().height()
        p_start = max(int(y0 // self.page_height_hint) - 2, 0)
        p_end = min(int(y1 // self.page_height_hint) + 2, self.pdf_doc.page_count - 1)
        for i in range(self.pdf_doc.page_count):
            item = self.inner_layout.itemAt(i)
            if p_start <= i <= p_end:
                if i not in self.loaded_pages:
                    self.load_page(i)
            else:
                if i in self.loaded_pages:
                    self.highlight_data_dict[i] = self.loaded_pages[i].highlights
                    w = self.loaded_pages.pop(i)
                    # 只移除label，不删居中容器
                    for child in item.widget().children():
                        if isinstance(child, QLabel):
                            child.setParent(None)
        while len(self.loaded_pages) > self.max_pages_mem:
            farthest = max(self.loaded_pages, key=lambda idx: abs((p_start+p_end)//2-idx))
            self.highlight_data_dict[farthest] = self.loaded_pages[farthest].highlights
            w = self.loaded_pages.pop(farthest)
            for j in range(self.inner_layout.count()):
                container = self.inner_layout.itemAt(j).widget()
                for child in container.children():
                    if isinstance(child, QLabel):
                        child.setParent(None)

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
        highlight_data = self.highlight_data_dict.get(idx, [])
        label = WordHighlightPDFPage(page, qimg, idx, self.highlight_colors, self, highlight_data)
        label.setMinimumHeight(qimg.height())
        label.setMaximumHeight(qimg.height())
        # --------- 居中容器 -------------
        center_widget = QWidget()
        hbox = QHBoxLayout(center_widget)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setAlignment(Qt.AlignHCenter)
        hbox.addWidget(label)
        self.inner_layout.insertWidget(idx, center_widget)
        # --------------------------------
        self.loaded_pages[idx] = label

    def update_pages_and_keep_mouse_focus(self, page_idx, mouse_pos, old_zoom):
        if not self.pdf_doc:
            return
        old_zoom_factor = self.get_dynamic_zoom() / self.user_zoom
        page = self.pdf_doc.load_page(page_idx)
        pdf_rect = page.rect
        qimg_w_old = int(pdf_rect.width * old_zoom_factor)
        qimg_h_old = int(pdf_rect.height * old_zoom_factor)
        mouse_x_frac = mouse_pos.x() / max(1, qimg_w_old)
        mouse_y_frac = mouse_pos.y() / max(1, qimg_h_old)
        self.reload_pages()
        label = self.loaded_pages.get(page_idx)
        if label:
            qimg_w_new = label.base_qimg.width()
            qimg_h_new = label.base_qimg.height()
            # 需要找到居中容器的位置
            for i in range(self.inner_layout.count()):
                container = self.inner_layout.itemAt(i).widget()
                if label in container.children():
                    label_pos = container.pos()
                    break
            else:
                label_pos = label.pos()
            target_x = label_pos.x() + mouse_x_frac * qimg_w_new
            target_y = label_pos.y() + mouse_y_frac * qimg_h_new
            viewport = self.scroll.viewport()
            vx = max(0, int(target_x - viewport.width() / 2))
            vy = max(0, int(target_y - viewport.height() / 2))
            self.scroll.horizontalScrollBar().setValue(vx)
            self.scroll.verticalScrollBar().setValue(vy)

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
            # 找到label的居中容器
            for i in range(self.inner_layout.count()):
                container = self.inner_layout.itemAt(i).widget()
                if label in container.children():
                    self.scroll.ensureWidgetVisible(container)
                    break
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
