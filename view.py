#!/usr/bin/env python3
"""
Professional Image Viewer Application - Enhanced Version

Features:
- High-performance image display with smooth zoom, rotation, and navigation
- Advanced cropping with aspect ratio locking and custom ratios
- Background removal integration with remove.bg API
- Professional UI with customizable toolbar, menus, and status bar
- Comprehensive settings management with persistence
- Multi-language support (English, Spanish, French)
- Keyboard shortcuts for all major functions
- Recent files menu
- Image metadata display (EXIF support)
- Slideshow mode
- Image comparison (before/after)
"""

import sys
import os
import platform
import webbrowser
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy, QFileDialog, QToolBar,
    QStatusBar, QToolButton, QFrame, QStyle, QMessageBox, QDialog,
    QFormLayout, QDialogButtonBox, QMenu, QLineEdit, QColorDialog,
    QSpinBox, QComboBox, QSlider, QProgressBar, QGroupBox
)
from PySide6.QtGui import (
    QPixmap, QImageReader, QTransform, QIcon, QPalette, QKeySequence,
    QClipboard, QColor, QPainter, QImage, QAction, QActionGroup,
    QFont, QFontMetrics, QGuiApplication, QTextDocument
)
from PySide6.QtCore import (
    Qt, QDir, QStandardPaths, QFile, QFileInfo, QSize, QSettings,
    QDateTime, QEvent, QRect, QPoint, QRectF, QTimer, QTranslator,
    QLocale, Signal, Slot, QThread, QObject, QSizeF
)

# Attempt to import optional dependencies
try:
    import send2trash
    SEND2TRASH_AVAILABLE = True
except ImportError:
    SEND2TRASH_AVAILABLE = False
    print("Note: 'send2trash' not available - deletion will be permanent")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Note: 'requests' not available - background removal disabled")

try:
    from PIL import Image, ImageQt, ExifTags
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Note: 'Pillow' not available - EXIF metadata and advanced image processing disabled")


class WorkerSignals(QObject):
    """Signals for background workers"""
    finished = Signal()
    error = Signal(str)
    result = Signal(object)
    progress = Signal(int)


class RemoveBgWorker(QThread):
    """Worker thread for remove.bg API calls"""
    def __init__(self, image_path, api_key):
        super().__init__()
        self.image_path = image_path
        self.api_key = api_key
        self.signals = WorkerSignals()

    def run(self):
        try:
            with open(self.image_path, 'rb') as img_file:
                response = requests.post(
                    'https://api.remove.bg/v1.0/removebg',
                    files={'image_file': img_file},
                    data={'size': 'auto'},
                    headers={'X-Api-Key': self.api_key},
                    timeout=30
                )
                response.raise_for_status()
                self.signals.result.emit(response.content)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class ApiKeyDialog(QDialog):
    """Dialog for setting remove.bg API key"""
    def __init__(self, current_api_key="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("API Key Configuration"))
        self.setWindowIcon(QIcon.fromTheme("preferences-system"))
        
        layout = QFormLayout(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setText(current_api_key)
        self.api_key_input.setPlaceholderText(self.tr("Enter your remove.bg API key"))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        
        self.show_key_checkbox = QToolButton(self)
        self.show_key_checkbox.setText(self.tr("Show"))
        self.show_key_checkbox.setCheckable(True)
        self.show_key_checkbox.toggled.connect(self.toggle_key_visibility)
        
        key_layout = QHBoxLayout()
        key_layout.addWidget(self.api_key_input)
        key_layout.addWidget(self.show_key_checkbox)
        
        layout.addRow(self.tr("API Key:"), key_layout)
        
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        
        self.setMinimumWidth(400)
        self.setModal(True)

    def toggle_key_visibility(self, checked):
        """Toggle between showing and hiding the API key"""
        self.api_key_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def get_api_key(self):
        """Get the sanitized API key from dialog"""
        return self.api_key_input.text().strip()


class CropOverlay(QWidget):
    """Advanced overlay for crop selection with darkened outside area and resize handles"""
    cropChanged = Signal(QRect)
    cropApplied = Signal()
    cropCancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.crop_rect = QRect()
        self.dragging = False
        self.resizing = False
        self.resize_handle_size = 12
        self.handle_hover = None
        self.ratio = None
        self.min_crop_size = 20
        self.setFocusPolicy(Qt.StrongFocus)
        self.grid_enabled = False
        self.guide_lines_enabled = True
        self.setMouseTracking(True)

    def set_crop_rect(self, rect):
        """Set the current crop rectangle"""
        self.crop_rect = rect.normalized()
        self.cropChanged.emit(self.crop_rect)
        self.update()

    def set_ratio(self, ratio):
        """Set the aspect ratio for cropping (None for free ratio)"""
        self.ratio = ratio
        if self.ratio and not self.crop_rect.isNull():
            self._constrain_to_ratio()

    def set_grid_enabled(self, enabled):
        """Enable/disable grid display"""
        self.grid_enabled = enabled
        self.update()

    def set_guide_lines_enabled(self, enabled):
        """Enable/disable guide lines (rule of thirds)"""
        self.guide_lines_enabled = enabled
        self.update()

    def _constrain_to_ratio(self):
        """Adjust current crop rectangle to maintain aspect ratio"""
        if not self.ratio or self.crop_rect.isNull():
            return
            
        w, h = self.ratio
        current_width = self.crop_rect.width()
        new_height = int(current_width * h / w)
        
        # Keep the center point
        center = self.crop_rect.center()
        new_rect = QRect()
        new_rect.setWidth(current_width)
        new_rect.setHeight(new_height)
        new_rect.moveCenter(center)
        
        # Ensure the new rect is within bounds
        bounded_rect = new_rect.intersected(QRect(QPoint(0, 0), self.size()))
        if not bounded_rect.isNull():
            self.crop_rect = bounded_rect
            self.cropChanged.emit(self.crop_rect)
            self.update()

    def handle_positions(self):
        """Return positions for 8 resize handles (corners and edges)"""
        r = self.crop_rect
        s = self.resize_handle_size
        return [
            r.topLeft(),                                   # Top-left
            r.topRight() - QPoint(s, 0),                  # Top-right
            r.bottomLeft() - QPoint(0, s),                # Bottom-left
            r.bottomRight() - QPoint(s, s),              # Bottom-right
            QPoint(r.center().x() - s//2, r.top()),      # Top-center
            QPoint(r.right() - s, r.center().y() - s//2), # Right-center
            QPoint(r.center().x() - s//2, r.bottom() - s), # Bottom-center
            QPoint(r.left(), r.center().y() - s//2)       # Left-center
        ]

    def get_cursor_for_handle(self, handle_idx):
        """Get appropriate cursor for each resize handle"""
        if handle_idx in [0, 3]:  # Top-left and bottom-right
            return Qt.SizeFDiagCursor
        elif handle_idx in [1, 2]:  # Top-right and bottom-left
            return Qt.SizeBDiagCursor
        elif handle_idx in [4, 6]:  # Top-center and bottom-center
            return Qt.SizeVerCursor
        elif handle_idx in [5, 7]:  # Right-center and left-center
            return Qt.SizeHorCursor
        return Qt.ArrowCursor

    def paintEvent(self, event):
        """Custom painting of the overlay"""
        if self.crop_rect.isNull():
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Darken outside crop area
        outer_path = QPainterPath()
        outer_path.addRect(QRectF(self.rect()))
        inner_path = QPainterPath()
        inner_path.addRect(QRectF(self.crop_rect))
        painter.fillPath(outer_path - inner_path, QColor(0, 0, 0, 160))
        
        # Draw crop border
        border_pen = QPen(QColor(255, 255, 255, 220), 1.5, Qt.DashLine)
        painter.setPen(border_pen)
        painter.drawRect(self.crop_rect)
        
        # Draw resize handles
        handle_brush = QBrush(QColor(255, 255, 255))
        handle_pen = QPen(QColor(0, 0, 0, 150), 1)
        painter.setPen(handle_pen)
        
        for pos in self.handle_positions():
            handle_rect = QRect(pos, QSize(self.resize_handle_size, self.resize_handle_size))
            painter.setBrush(handle_brush)
            painter.drawRect(handle_rect)
        
        # Draw grid if enabled
        if self.grid_enabled and not self.crop_rect.isNull():
            grid_pen = QPen(QColor(255, 255, 255, 60), 1, Qt.DotLine)
            painter.setPen(grid_pen)
            
            # Draw 3x3 grid
            for i in range(1, 3):
                x = self.crop_rect.left() + i * self.crop_rect.width() // 3
                painter.drawLine(x, self.crop_rect.top(), x, self.crop_rect.bottom())
                
                y = self.crop_rect.top() + i * self.crop_rect.height() // 3
                painter.drawLine(self.crop_rect.left(), y, self.crop_rect.right(), y)
        
        # Draw guide lines (rule of thirds)
        if self.guide_lines_enabled and not self.crop_rect.isNull():
            guide_pen = QPen(QColor(255, 100, 100, 180), 1.5, Qt.DashLine)
            painter.setPen(guide_pen)
            
            # Vertical guides
            for i in [1, 2]:
                x = self.crop_rect.left() + i * self.crop_rect.width() // 3
                painter.drawLine(x, self.crop_rect.top(), x, self.crop_rect.bottom())
            
            # Horizontal guides
            for i in [1, 2]:
                y = self.crop_rect.top() + i * self.crop_rect.height() // 3
                painter.drawLine(self.crop_rect.left(), y, self.crop_rect.right(), y)

    def mousePressEvent(self, event):
        """Handle mouse press for dragging/resizing"""
        if event.button() != Qt.LeftButton:
            return
            
        self.handle_hover = None
        for idx, pos in enumerate(self.handle_positions()):
            handle_rect = QRect(pos, QSize(self.resize_handle_size, self.resize_handle_size))
            if handle_rect.contains(event.pos()):
                self.resizing = True
                self.handle_hover = idx
                self.drag_start_pos = event.pos()
                self.crop_start_rect = QRect(self.crop_rect)
                self.setCursor(self.get_cursor_for_handle(idx))
                return
                
        if self.crop_rect.contains(event.pos()):
            self.dragging = True
            self.drag_start_pos = event.pos()
            self.crop_start_rect = QRect(self.crop_rect)
            self.setCursor(Qt.SizeAllCursor)
        else:
            # Start new crop
            self.crop_rect = QRect(event.pos(), QSize())
            self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse movement for dragging/resizing"""
        if not (self.dragging or self.resizing):
            # Update cursor based on handle hover
            cursor = Qt.ArrowCursor
            for idx, pos in enumerate(self.handle_positions()):
                handle_rect = QRect(pos, QSize(self.resize_handle_size, self.resize_handle_size))
                if handle_rect.contains(event.pos()):
                    cursor = self.get_cursor_for_handle(idx)
                    break
            self.setCursor(cursor)
            return
            
        if self.resizing and self.handle_hover is not None:
            delta = event.pos() - self.drag_start_pos
            rect = QRect(self.crop_start_rect)
            
            # Resize based on which handle is being dragged
            if self.handle_hover == 0:  # top-left
                rect.setTopLeft(rect.topLeft() + delta)
            elif self.handle_hover == 1:  # top-right
                rect.setTopRight(rect.topRight() + delta)
            elif self.handle_hover == 2:  # bottom-left
                rect.setBottomLeft(rect.bottomLeft() + delta)
            elif self.handle_hover == 3:  # bottom-right
                rect.setBottomRight(rect.bottomRight() + delta)
            elif self.handle_hover == 4:  # top-center
                rect.setTop(rect.top() + delta.y())
            elif self.handle_hover == 5:  # right-center
                rect.setRight(rect.right() + delta.x())
            elif self.handle_hover == 6:  # bottom-center
                rect.setBottom(rect.bottom() + delta.y())
            elif self.handle_hover == 7:  # left-center
                rect.setLeft(rect.left() + delta.x())
            
            # Constrain to aspect ratio if set
            if self.ratio:
                w, h = self.ratio
                if self.handle_hover in [0, 1, 2, 3]:  # Corner handles
                    width = rect.width()
                    height = int(width * h / w)
                    
                    if self.handle_hover in [0, 1]:  # Top handles
                        rect.setTop(rect.bottom() - height)
                    else:  # Bottom handles
                        rect.setBottom(rect.top() + height)
                else:  # Edge handles
                    if self.handle_hover in [4, 6]:  # Top or bottom edge
                        width = int(rect.height() * w / h)
                        rect.setWidth(width)
                    else:  # Left or right edge
                        height = int(rect.width() * h / w)
                        rect.setHeight(height)
            
            # Ensure minimum size
            if rect.width() < self.min_crop_size:
                if self.handle_hover in [0, 2, 7]:  # Left handles
                    rect.setLeft(rect.right() - self.min_crop_size)
                else:
                    rect.setRight(rect.left() + self.min_crop_size)
                    
            if rect.height() < self.min_crop_size:
                if self.handle_hover in [0, 1, 4]:  # Top handles
                    rect.setTop(rect.bottom() - self.min_crop_size)
                else:
                    rect.setBottom(rect.top() + self.min_crop_size)
            
            # Ensure rect stays within bounds
            bounded_rect = rect.intersected(QRect(QPoint(0, 0), self.size()))
            if not bounded_rect.isNull():
                self.crop_rect = bounded_rect.normalized()
                self.update()
                
        elif self.dragging:
            delta = event.pos() - self.drag_start_pos
            rect = QRect(self.crop_start_rect)
            rect.translate(delta)
            
            # Ensure rect stays within bounds
            bounded_rect = rect.intersected(QRect(QPoint(0, 0), self.size()))
            if not bounded_rect.isNull():
                self.crop_rect = bounded_rect
                self.update()

    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.resizing = False
            self.handle_hover = None
            self.setCursor(Qt.ArrowCursor)
            
            if self.crop_rect.width() < 5 or self.crop_rect.height() < 5:
                self.crop_rect = QRect()
                self.update()

    def keyPressEvent(self, event):
        """Handle key presses for crop operations"""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not self.crop_rect.isNull():
                self.cropApplied.emit()
        elif event.key() == Qt.Key_Escape:
            self.cropCancelled.emit()
        elif event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            # Move crop rect with arrow keys
            if self.crop_rect.isNull():
                return
                
            step = 1 if event.modifiers() & Qt.ShiftModifier else 5
            dx = 0
            dy = 0
            
            if event.key() == Qt.Key_Left:
                dx = -step
            elif event.key() == Qt.Key_Right:
                dx = step
            elif event.key() == Qt.Key_Up:
                dy = -step
            elif event.key() == Qt.Key_Down:
                dy = step
                
            new_rect = self.crop_rect.translated(dx, dy)
            bounded_rect = new_rect.intersected(QRect(QPoint(0, 0), self.size()))
            if not bounded_rect.isNull():
                self.crop_rect = bounded_rect
                self.update()
        else:
            super().keyPressEvent(event)


class ImageViewer(QMainWindow):
    """Main application window for the Professional Image Viewer"""
    
    VERSION = "2.0.0"
    ORGANIZATION = "DigitalVision"
    APPLICATION = "Professional Image Viewer"
    
    # Signals
    imageLoaded = Signal(str)
    imageSaved = Signal(str)
    backgroundRemoved = Signal()
    
    def __init__(self, image_path=None):
        super().__init__()
        
        # Initialize application state
        self.current_image_path = None
        self.current_image_index = -1
        self.image_files_in_directory = []
        self.recent_files = []
        self.max_recent_files = 10
        self.scale_factor = 1.0
        self.rotation_angle = 0
        self.initial_image_to_load = image_path
        self.pixmap = QPixmap()
        self.original_pixmap = QPixmap()  # Keep original for comparison
        self.is_fullscreen = False
        self.image_modified_by_bg_removal = False
        self.image_modified_by_crop = False
        self.remove_bg_api_key = ""
        self.viewer_bg_color = QColor(Qt.darkGray)
        self.slideshow_timer = QTimer(self)
        self.slideshow_interval = 3000  # 3 seconds
        self.is_slideshow_active = False
        self.current_language = "en"
        self.translator = QTranslator()
        
        # Crop-related state
        self.is_cropping = False
        self.crop_origin_point_on_label = None
        self.current_crop_ratio = None
        
        # Comparison mode
        self.comparison_mode = False
        self.comparison_slider_pos = 50  # 0-100
        
        # Initialize UI and settings
        self._initialize_application()
        self._load_settings()
        self._setup_ui()
        
        # Load initial image if provided
        self._load_initial_image()
        
        # Setup connections
        self.slideshow_timer.timeout.connect(self.next_image_manual)
        self.imageLoaded.connect(self._on_image_loaded)
        self.imageSaved.connect(self._on_image_saved)
        self.backgroundRemoved.connect(self._on_background_removed)

    def _initialize_application(self):
        """Set application metadata and organization"""
        QApplication.setOrganizationName(self.ORGANIZATION)
        QApplication.setApplicationName(self.APPLICATION)
        QApplication.setApplicationVersion(self.VERSION)
        
        # Set default icon theme based on platform
        if platform.system() == "Linux":
            QIcon.setThemeName("breeze")
        else:
            QIcon.setThemeName("Fusion")

    def _load_settings(self):
        """Load persistent application settings"""
        settings = QSettings()
        
        # Window geometry
        self.restoreGeometry(settings.value("window_geometry"))
        self.restoreState(settings.value("window_state"))
        
        # Application settings
        self.remove_bg_api_key = settings.value("remove_bg_api_key", "", type=str)
        self.recent_files = settings.value("recent_files", []) or []
        # Ensure recent_files is always a list
        if isinstance(self.recent_files, str):
            # Split by separator if needed, or wrap in list
            if self.recent_files.strip() == "":
                self.recent_files = []
            else:
                # Try splitting by common separators
                if "\n" in self.recent_files:
                    self.recent_files = [f for f in self.recent_files.splitlines() if f.strip()]
                elif "," in self.recent_files:
                    self.recent_files = [f.strip() for f in self.recent_files.split(",") if f.strip()]
                else:
                    self.recent_files = [self.recent_files.strip()]
        elif not isinstance(self.recent_files, list):
            self.recent_files = list(self.recent_files)
        self.current_language = settings.value("language", "en", type=str)
        
        # Viewer settings
        default_bg_color = self.palette().color(QPalette.Window)
        if not default_bg_color.isValid():
            default_bg_color = QColor(Qt.lightGray)
            
        bg_color_name = settings.value("viewer_background_color", default_bg_color.name(), type=str)
        loaded_color = QColor(bg_color_name)
        self.viewer_bg_color = loaded_color if loaded_color.isValid() else default_bg_color
        
        # Slideshow settings
        self.slideshow_interval = settings.value("slideshow_interval", 3000, type=int)

    def _save_settings(self):
        """Save application settings"""
        settings = QSettings()
        
        # Window state
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        
        # Application settings
        settings.setValue("remove_bg_api_key", self.remove_bg_api_key)
        settings.setValue("recent_files", self.recent_files)
        settings.setValue("language", self.current_language)
        
        # Viewer settings
        settings.setValue("viewer_background_color", self.viewer_bg_color.name())
        
        # Slideshow settings
        settings.setValue("slideshow_interval", self.slideshow_interval)

    def _setup_ui(self):
        """Initialize the main application UI"""
        self.setWindowTitle(f"{self.APPLICATION} {self.VERSION}")
        self.setMinimumSize(640, 480)
        
        # Central widget setup
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main layout
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Image display components
        self._setup_image_display()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Progress bar for operations
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        # Create actions, menus and toolbar
        self._create_actions()
        self.load_language(self.current_language)
        self._create_menus()
        self._create_toolbar()
        
        # Apply initial settings
        self.apply_background_color(self.viewer_bg_color)
        self.status_bar.showMessage(self.tr("Ready"))
        self.update_actions_state()
        self.setFocusPolicy(Qt.StrongFocus)

    def _setup_image_display(self):
        """Setup the image display components"""
        # Main image label
        self.image_label = QLabel()
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.installEventFilter(self)
        
        # Comparison label (for before/after)
        self.comparison_label = QLabel()
        self.comparison_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.comparison_label.setScaledContents(False)
        self.comparison_label.setAlignment(Qt.AlignCenter)
        self.comparison_label.hide()
        
        # Container widget for comparison mode
        self.comparison_container = QWidget()
        self.comparison_layout = QHBoxLayout(self.comparison_container)
        self.comparison_layout.setContentsMargins(0, 0, 0, 0)
        self.comparison_layout.setSpacing(0)
        self.comparison_layout.addWidget(self.image_label)
        self.comparison_layout.addWidget(self.comparison_label)
        
        # Scroll area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(False)
        self.main_layout.addWidget(self.scroll_area)
        
        # Comparison slider
        self.comparison_slider = QSlider(Qt.Horizontal)
        self.comparison_slider.setRange(0, 100)
        self.comparison_slider.setValue(50)
        self.comparison_slider.valueChanged.connect(self.update_comparison_view)
        self.comparison_slider.hide()
        self.main_layout.addWidget(self.comparison_slider)
        
        # Crop overlay
        self.crop_overlay = CropOverlay(self.image_label)
        self.crop_overlay.hide()
        self.crop_overlay.cropApplied.connect(self.apply_crop_from_selection)
        self.crop_overlay.cropCancelled.connect(lambda: self.toggle_crop_mode(False))

    def _create_actions(self):
        """Create all application actions"""
        # File actions
        self._create_file_actions()
        
        # Edit actions
        self._create_edit_actions()
        
        # View actions
        self._create_view_actions()
        
        # Navigate actions
        self._create_navigate_actions()
        
        # Settings actions
        self._create_settings_actions()
        
        # Crop actions
        self._create_crop_actions()
        
        # Slideshow actions
        self._create_slideshow_actions()
        
        # Help actions
        self._create_help_actions()

    def _create_file_actions(self):
        """Create file-related actions"""
        self.open_action = self._create_action(
            "document-open", 
            self.tr("&Open..."), 
            self.tr("Open an image file"),
            QKeySequence.Open,
            self.open_image_dialog
        )
        
        self.save_action = self._create_action(
            "document-save", 
            self.tr("&Save"), 
            self.tr("Save the current image"),
            QKeySequence.Save,
            self.save_image
        )
        
        self.save_as_action = self._create_action(
            "document-save-as", 
            self.tr("Save &As..."), 
            self.tr("Save the current image with a new name"),
            QKeySequence.SaveAs,
            self.save_image_as
        )
        
        self.exit_action = self._create_action(
            "application-exit", 
            self.tr("&Exit"), 
            self.tr("Exit the application"),
            QKeySequence.Quit,
            self.close
        )
        
        # Recent files actions (will be populated dynamically)
        self.recent_file_actions = []
        for i in range(self.max_recent_files):
            action = QAction(self, visible=False, triggered=self._open_recent_file)
            self.recent_file_actions.append(action)
        
        self.clear_recent_action = self._create_action(
            "edit-clear",
            self.tr("Clear Recent Files"),
            self.tr("Clear recent files list"),
            None,
            self.clear_recent_files
        )

    def _create_edit_actions(self):
        """Create edit-related actions"""
        self.copy_action = self._create_action(
            "edit-copy", 
            self.tr("&Copy Image"), 
            self.tr("Copy image to clipboard"),
            QKeySequence.Copy,
            self.copy_image_to_clipboard
        )
        
        self.remove_bg_action = self._create_action(
            "edit-clear", 
            self.tr("Remove &Background"), 
            self.tr("Remove image background using remove.bg"),
            QKeySequence("Ctrl+B"),
            self.process_remove_background
        )
        
        self.delete_action = self._create_action(
            "edit-delete", 
            self.tr("&Delete Image"), 
            self.tr("Move current image to trash"),
            QKeySequence.Delete,
            self.delete_current_image
        )
        
        self.compare_action = self._create_action(
            "document-edit",
            self.tr("Compare"),
            self.tr("Compare original and modified versions"),
            QKeySequence("Ctrl+C"),
            self.toggle_comparison_mode
        )
        self.compare_action.setCheckable(True)

    def _create_view_actions(self):
        """Create view-related actions"""
        self.zoom_in_action = self._create_action(
            "zoom-in", 
            self.tr("Zoom &In"), 
            self.tr("Zoom in on the image"),
            QKeySequence.ZoomIn,
            self.zoom_in
        )
        
        self.zoom_out_action = self._create_action(
            "zoom-out", 
            self.tr("Zoom &Out"), 
            self.tr("Zoom out from the image"),
            QKeySequence.ZoomOut,
            self.zoom_out
        )
        
        self.fit_window_action = self._create_action(
            "zoom-fit-best", 
            self.tr("&Fit to Window"), 
            self.tr("Fit image to window size"),
            QKeySequence("F"),
            self.fit_to_window
        )
        
        self.actual_size_action = self._create_action(
            "zoom-original", 
            self.tr("&Actual Size"), 
            self.tr("View image at 100% scale"),
            QKeySequence("Ctrl+0"),
            self.actual_size
        )
        
        self.rotate_left_action = self._create_action(
            "object-rotate-left", 
            self.tr("Rotate &Left"), 
            self.tr("Rotate image 90° counter-clockwise"),
            QKeySequence("Ctrl+L"),
            self.rotate_left
        )
        
        self.rotate_right_action = self._create_action(
            "object-rotate-right", 
            self.tr("Rotate &Right"), 
            self.tr("Rotate image 90° clockwise"),
            QKeySequence("Ctrl+R"),
            self.rotate_right
        )
        
        self.fullscreen_action = self._create_action(
            "view-fullscreen", 
            self.tr("&Fullscreen"), 
            self.tr("Toggle fullscreen mode"),
            QKeySequence("F11"),
            self.toggle_fullscreen
        )
        self.fullscreen_action.setCheckable(True)
        
        self.change_bg_color_action = self._create_action(
            "preferences-desktop-theme", 
            self.tr("Change &Background Color..."), 
            self.tr("Change viewer background color"),
            None,
            self.show_change_background_color_dialog
        )
        
        self.properties_action = self._create_action(
            "document-properties", 
            self.tr("Image &Properties..."), 
            self.tr("Show image properties"),
            QKeySequence("Alt+Return"),
            self.show_image_properties
        )

    def _create_navigate_actions(self):
        """Create navigation-related actions"""
        self.prev_action = self._create_action(
            "go-previous", 
            self.tr("&Previous Image"), 
            self.tr("Go to previous image in folder"),
            QKeySequence("Left"),
            self.prev_image_manual
        )
        
        self.next_action = self._create_action(
            "go-next", 
            self.tr("&Next Image"), 
            self.tr("Go to next image in folder"),
            QKeySequence("Right"),
            self.next_image_manual
        )
        
        self.first_action = self._create_action(
            "go-first",
            self.tr("&First Image"),
            self.tr("Go to first image in folder"),
            QKeySequence("Home"),
            lambda: self.go_to_image(0)
        )
        
        self.last_action = self._create_action(
            "go-last",
            self.tr("&Last Image"),
            self.tr("Go to last image in folder"),
            QKeySequence("End"),
            lambda: self.go_to_image(-1)
        )

    def _create_settings_actions(self):
        """Create settings-related actions"""
        self.set_api_key_action = self._create_action(
            "configure", 
            self.tr("Set API &Key..."), 
            self.tr("Set remove.bg API key"),
            None,
            self.show_set_api_key_dialog
        )
        
        # Language actions
        self.language_group = QActionGroup(self)
        
        self.language_en_action = QAction("English", self.language_group)
        self.language_en_action.setCheckable(True)
        self.language_en_action.triggered.connect(lambda: self.set_language("en"))
        
        self.language_es_action = QAction("Español", self.language_group)
        self.language_es_action.setCheckable(True)
        self.language_es_action.triggered.connect(lambda: self.set_language("es"))
        
        self.language_fr_action = QAction("Français", self.language_group)
        self.language_fr_action.setCheckable(True)
        self.language_fr_action.triggered.connect(lambda: self.set_language("fr"))
        
        # Set current language
        if self.current_language == "es":
            self.language_es_action.setChecked(True)
        elif self.current_language == "fr":
            self.language_fr_action.setChecked(True)
        else:
            self.language_en_action.setChecked(True)

    def _create_crop_actions(self):
        """Create crop-related actions"""
        self.crop_mode_action = self._create_action(
            "transform-crop", 
            self.tr("&Crop Mode"), 
            self.tr("Toggle crop selection mode"),
            QKeySequence("Ctrl+Shift+C"),
            self.toggle_crop_mode
        )
        self.crop_mode_action.setCheckable(True)
        
        # Crop ratio actions
        self.crop_free_action = QAction(self.tr("&Free Crop"), self)
        self.crop_free_action.setCheckable(True)
        self.crop_free_action.triggered.connect(lambda: self.set_crop_ratio(None))
        
        self.crop_1_1_action = QAction(self.tr("Crop &1:1 (Square)"), self)
        self.crop_1_1_action.setCheckable(True)
        self.crop_1_1_action.triggered.connect(lambda: self.set_crop_ratio((1, 1)))
        
        self.crop_4_3_action = QAction(self.tr("Crop &4:3"), self)
        self.crop_4_3_action.setCheckable(True)
        self.crop_4_3_action.triggered.connect(lambda: self.set_crop_ratio((4, 3)))
        
        self.crop_3_2_action = QAction(self.tr("Crop &3:2"), self)
        self.crop_3_2_action.setCheckable(True)
        self.crop_3_2_action.triggered.connect(lambda: self.set_crop_ratio((3, 2)))
        
        self.crop_16_9_action = QAction(self.tr("Crop &16:9"), self)
        self.crop_16_9_action.setCheckable(True)
        self.crop_16_9_action.triggered.connect(lambda: self.set_crop_ratio((16, 9)))
        
        self.crop_custom_action = QAction(self.tr("&Custom Ratio..."), self)
        self.crop_custom_action.triggered.connect(self.show_custom_ratio_dialog)
        
        # Grid and guides actions
        self.crop_show_grid_action = QAction(self.tr("Show &Grid"), self)
        self.crop_show_grid_action.setCheckable(True)
        self.crop_show_grid_action.setChecked(False)
        self.crop_show_grid_action.triggered.connect(
            lambda: self.crop_overlay.set_grid_enabled(self.crop_show_grid_action.isChecked()))
        
        self.crop_show_guides_action = QAction(self.tr("Show &Guides"), self)
        self.crop_show_guides_action.setCheckable(True)
        self.crop_show_guides_action.setChecked(True)
        self.crop_show_guides_action.triggered.connect(
            lambda: self.crop_overlay.set_guide_lines_enabled(self.crop_show_guides_action.isChecked()))
        
        # Group for exclusive checking of crop ratio actions
        self.crop_ratio_group = QActionGroup(self)
        self.crop_ratio_group.addAction(self.crop_free_action)
        self.crop_ratio_group.addAction(self.crop_1_1_action)
        self.crop_ratio_group.addAction(self.crop_4_3_action)
        self.crop_ratio_group.addAction(self.crop_3_2_action)
        self.crop_ratio_group.addAction(self.crop_16_9_action)
        self.crop_ratio_group.setExclusive(True)
        self.crop_free_action.setChecked(True)  # Default to free crop
        
        self.apply_crop_action = self._create_action(
            "dialog-ok-apply", 
            self.tr("&Apply Crop"), 
            self.tr("Apply the current crop selection"),
            QKeySequence("Ctrl+Return"),
            self.apply_crop_from_selection
        )
        self.apply_crop_action.setEnabled(False)

    def _create_slideshow_actions(self):
        """Create slideshow-related actions"""
        self.slideshow_start_action = self._create_action(
            "media-playback-start",
            self.tr("Start &Slideshow"),
            self.tr("Start slideshow of images in current folder"),
            QKeySequence("Ctrl+Shift+S"),
            self.start_slideshow
        )
        
        self.slideshow_stop_action = self._create_action(
            "media-playback-stop",
            self.tr("Stop Slideshow"),
            self.tr("Stop the running slideshow"),
            QKeySequence("Esc"),
            self.stop_slideshow
        )
        self.slideshow_stop_action.setEnabled(False)
        
        self.slideshow_settings_action = self._create_action(
            "configure",
            self.tr("Slideshow &Settings..."),
            self.tr("Configure slideshow settings"),
            None,
            self.show_slideshow_settings
        )

    def _create_help_actions(self):
        """Create help-related actions"""
        self.help_action = self._create_action(
            "help-contents",
            self.tr("&Help"),
            self.tr("Show application help"),
            QKeySequence.HelpContents,
            self.show_help
        )
        
        self.about_action = self._create_action(
            "help-about",
            self.tr("&About"),
            self.tr("Show about information"),
            None,
            self.show_about
        )
        
        self.about_qt_action = self._create_action(
            "qtlogo",
            self.tr("About &Qt"),
            self.tr("Show about Qt information"),
            None,
            QApplication.aboutQt
        )

    def _create_action(self, icon_name, text, tooltip, shortcut, callback):
        """Helper to create standardized actions"""
        # Try to get icon from theme, fall back to standard icons
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            # Try to get a standard pixmap as a fallback
            standard_icon_enum = getattr(QStyle, f"SP_{icon_name.replace('-', '_').title()}", None)
            if standard_icon_enum:
                icon = self.style().standardIcon(standard_icon_enum)
            else:  # Final fallback to a generic icon
                icon = QIcon.fromTheme("application-x-executable")

        action = QAction(icon, text, self)
        action.setToolTip(tooltip)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        return action

    def _create_menus(self):
        """Create the application menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu(self.tr('&File'))
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        
        # Recent files submenu
        self.recent_menu = file_menu.addMenu(self.tr("Open &Recent"))
        self.update_recent_files_menu()
        
        file_menu.addSeparator()
        file_menu.addAction(self.properties_action)
        file_menu.addSeparator()
        file_menu.addAction(self.delete_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu(self.tr('&Edit'))
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.remove_bg_action)
        edit_menu.addAction(self.compare_action)
        edit_menu.addSeparator()
        
        # Crop submenu
        crop_menu = edit_menu.addMenu(self.tr("&Crop"))
        crop_menu.addAction(self.crop_mode_action)
        crop_menu.addSeparator()
        crop_menu.addAction(self.crop_free_action)
        crop_menu.addAction(self.crop_1_1_action)
        crop_menu.addAction(self.crop_4_3_action)
        crop_menu.addAction(self.crop_3_2_action)
        crop_menu.addAction(self.crop_16_9_action)
        crop_menu.addAction(self.crop_custom_action)
        crop_menu.addSeparator()
        crop_menu.addAction(self.crop_show_grid_action)
        crop_menu.addAction(self.crop_show_guides_action)
        crop_menu.addSeparator()
        crop_menu.addAction(self.apply_crop_action)
        
        # View menu
        view_menu = menubar.addMenu(self.tr('&View'))
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.actual_size_action)
        view_menu.addAction(self.fit_window_action)
        view_menu.addSeparator()
        view_menu.addAction(self.rotate_left_action)
        view_menu.addAction(self.rotate_right_action)
        view_menu.addSeparator()
        view_menu.addAction(self.change_bg_color_action)
        view_menu.addSeparator()
        view_menu.addAction(self.fullscreen_action)
        
        # Navigate menu
        navigate_menu = menubar.addMenu(self.tr('&Navigate'))
        navigate_menu.addAction(self.prev_action)
        navigate_menu.addAction(self.next_action)
        navigate_menu.addAction(self.first_action)
        navigate_menu.addAction(self.last_action)
        navigate_menu.addSeparator()
        
        # Slideshow submenu
        slideshow_menu = navigate_menu.addMenu(self.tr("&Slideshow"))
        slideshow_menu.addAction(self.slideshow_start_action)
        slideshow_menu.addAction(self.slideshow_stop_action)
        slideshow_menu.addSeparator()
        slideshow_menu.addAction(self.slideshow_settings_action)
        
        # Settings menu
        settings_menu = menubar.addMenu(self.tr('&Settings'))
        settings_menu.addAction(self.set_api_key_action)
        settings_menu.addSeparator()
        
        # Language submenu
        language_menu = settings_menu.addMenu(self.tr("&Language"))
        language_menu.addAction(self.language_en_action)
        language_menu.addAction(self.language_es_action)
        language_menu.addAction(self.language_fr_action)
        
        # Help menu
        help_menu = menubar.addMenu(self.tr('&Help'))
        help_menu.addAction(self.help_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)
        help_menu.addAction(self.about_qt_action)

    def _create_toolbar(self):
        """Create the application toolbar"""
        self.toolbar = QToolBar(self.tr("Main Controls"))
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.tool_button_icon_size = QSize(32, 32)  # Larger icons for better visibility
        self.toolbar.setIconSize(self.tool_button_icon_size)
        
        # Add toolbar to bottom of window
        self.addToolBar(Qt.BottomToolBarArea, self.toolbar)
        
        # Container widget for better layout control
        toolbar_container_widget = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container_widget)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        toolbar_layout.setSpacing(8)
        toolbar_layout.addStretch(1)
        
        # Group actions by function
        file_actions = [self.open_action, self.save_action]
        zoom_actions = [self.zoom_out_action, self.zoom_in_action, 
                       self.fit_window_action, self.actual_size_action]
        navigate_actions = [self.first_action, self.prev_action, 
                          self.next_action, self.last_action]
        edit_actions = [self.rotate_left_action, self.rotate_right_action, 
                       self.remove_bg_action, self.compare_action,
                       self.crop_mode_action, self.apply_crop_action]
        slideshow_actions = [self.slideshow_start_action, self.slideshow_stop_action]
        view_actions = [self.change_bg_color_action, self.fullscreen_action]
        
        # Add action groups to toolbar
        self._add_actions_to_toolbar(toolbar_layout, file_actions)
        toolbar_layout.addWidget(self._create_separator())
        
        self._add_actions_to_toolbar(toolbar_layout, zoom_actions)
        toolbar_layout.addWidget(self._create_separator())
        
        self._add_actions_to_toolbar(toolbar_layout, navigate_actions)
        toolbar_layout.addWidget(self._create_separator())
        
        self._add_actions_to_toolbar(toolbar_layout, edit_actions)
        toolbar_layout.addWidget(self._create_separator())
        
        self._add_actions_to_toolbar(toolbar_layout, slideshow_actions)
        toolbar_layout.addWidget(self._create_separator())
        
        self._add_actions_to_toolbar(toolbar_layout, view_actions)
        
        toolbar_layout.addStretch(1)
        toolbar_container_widget.setLayout(toolbar_layout)
        self.toolbar.addWidget(toolbar_container_widget)

    def _add_actions_to_toolbar(self, layout, actions):
        """Add actions to toolbar with proper buttons"""
        for action in actions:
            button = QToolButton()
            button.setDefaultAction(action)
            button.setIconSize(self.tool_button_icon_size)
            # Remove text under icon, show icon only
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            # Set tooltip with shortcut if available
            tooltip = action.toolTip()
            if action.shortcut():
                tooltip += f" ({action.shortcut().toString()})"
            button.setToolTip(tooltip)
            layout.addWidget(button)

    def _create_separator(self):
        """Create a vertical separator for toolbar"""
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setMinimumHeight(32)
        return separator

    def _load_initial_image(self):
        """Load the initial image if provided"""
        if not self.initial_image_to_load:
            return
            
        if not QFile.exists(self.initial_image_to_load):
            self.status_bar.showMessage(
                self.tr("File not found: %s") % self.initial_image_to_load, 5000)
            return
            
        info = QFileInfo(self.initial_image_to_load)
        supported_formats = [bytes(fmt).decode().lower() 
                           for fmt in QImageReader.supportedImageFormats()]
                           
        if info.suffix().lower() in supported_formats:
            self.load_image(self.initial_image_to_load)
        else:
            self.status_bar.showMessage(
                self.tr("Unsupported file format: %s") % self.initial_image_to_load,
                5000
            )

    def load_image(self, file_path):
        """Load an image from file"""
        if not os.path.exists(file_path):
            self.status_bar.showMessage(self.tr("File not found: %s") % file_path, 5000)
            return False
            
        # Use Pillow if available for better format support and EXIF handling
        if PILLOW_AVAILABLE:
            try:
                pil_image = Image.open(file_path)
                
                # Handle EXIF orientation
                pil_image = self._apply_exif_orientation(pil_image)
                
                # Convert to QPixmap
                qimage = ImageQt.ImageQt(pil_image)
                new_pixmap = QPixmap.fromImage(qimage)
            except Exception as e:
                print(f"Pillow load error: {e}")
                # Fall back to Qt if Pillow fails
                new_pixmap = QPixmap(file_path)
        else:
            new_pixmap = QPixmap(file_path)
            
        if new_pixmap.isNull():
            self.status_bar.showMessage(
                self.tr("Failed to load image: %s") % os.path.basename(file_path),
                5000
            )
            return False
            
        self.pixmap = new_pixmap
        self.original_pixmap = QPixmap(new_pixmap)  # Keep original for comparison
        self.current_image_path = file_path
        
        # Add to recent files
        self._add_to_recent_files(file_path)
        
        # Reset image state
        self.scale_factor = 1.0
        self.rotation_angle = 0
        self.image_modified_by_bg_removal = False
        self.image_modified_by_crop = False
        
        # Update display and directory listing
        self.fit_to_window()
        self.load_directory_images(self.current_image_path)
        self.setWindowTitle(f"{os.path.basename(self.current_image_path)} - {self.APPLICATION}")
        self.update_actions_state()
        
        # Emit signal
        self.imageLoaded.emit(file_path)
        
        return True

    def _apply_exif_orientation(self, pil_image):
        """Apply EXIF orientation to image if available"""
        if not PILLOW_AVAILABLE:
            return pil_image
            
        try:
            exif = pil_image._getexif()
            if exif:
                orientation = exif.get(274)  # 274 is the orientation tag
                
                if orientation == 2:
                    pil_image = pil_image.transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 3:
                    pil_image = pil_image.rotate(180)
                elif orientation == 4:
                    pil_image = pil_image.rotate(180).transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 5:
                    pil_image = pil_image.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 6:
                    pil_image = pil_image.rotate(-90, expand=True)
                elif orientation == 7:
                    pil_image = pil_image.rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 8:
                    pil_image = pil_image.rotate(90, expand=True)
                    
        except Exception as e:
            print(f"Error applying EXIF orientation: {e}")
            
        return pil_image

    def load_directory_images(self, current_file_path):
        """Load all images in the current file's directory"""
        self.image_files_in_directory = []
        self.current_image_index = -1
        
        if not current_file_path or not os.path.exists(current_file_path):
            self.update_actions_state()
            return
            
        abs_path = os.path.abspath(current_file_path)
        directory = os.path.dirname(abs_path)
        
        if not os.path.isdir(directory):
            self.update_actions_state()
            return
            
        # Get supported formats
        supported_extensions = [f".{bytes(fmt).decode().lower()}" 
                              for fmt in QImageReader.supportedImageFormats()]
        
        try:
            # Build sorted list of supported images
            image_list = []
            for entry in sorted(os.listdir(directory), key=lambda s: s.lower()):
                full_path = os.path.join(directory, entry)
                if os.path.isfile(full_path):
                    ext = os.path.splitext(full_path)[1].lower()
                    if ext in supported_extensions:
                        image_list.append(os.path.normpath(full_path))
            
            self.image_files_in_directory = image_list
            normalized_path = os.path.normpath(abs_path)
            
            if normalized_path in self.image_files_in_directory:
                self.current_image_index = self.image_files_in_directory.index(normalized_path)
                
        except Exception as e:
            print(f"Error loading directory images: {e}")
            
        self.update_actions_state()

    def update_image_display(self):
        """Update the displayed image with current transformations"""
        if self.pixmap.isNull():
            self.image_label.clear()
            filename = os.path.basename(self.current_image_path) if self.current_image_path else ""
            
            if filename and self.status_bar.currentMessage().startswith("Failed to load"):
                return
            elif self.current_image_path:
                self.status_bar.showMessage(self.tr("Cannot display: %s") % filename)
            else:
                self.status_bar.showMessage(self.tr("No image to display"))
            return
            
        try:
            # Apply rotation
            transform = QTransform()
            transform.rotate(self.rotation_angle)
            rotated_pixmap = self.pixmap.transformed(transform, Qt.SmoothTransformation)
            
            # Calculate scale factor with minimum dimension check
            effective_scale = self.scale_factor
            min_dim = 1  # Minimum dimension after scaling
            
            target_width = rotated_pixmap.width() * effective_scale
            target_height = rotated_pixmap.height() * effective_scale
            
            if target_width < min_dim and rotated_pixmap.width() > 0:
                effective_scale = min_dim / rotated_pixmap.width()
                
            if target_height < min_dim and rotated_pixmap.height() > 0:
                effective_scale = max(effective_scale, min_dim / rotated_pixmap.height())
                
            # Calculate final dimensions
            new_width = max(min_dim, int(rotated_pixmap.width() * effective_scale))
            new_height = max(min_dim, int(rotated_pixmap.height() * effective_scale))
            
            # Scale the pixmap
            scaled_pixmap = rotated_pixmap.scaled(
                new_width, new_height, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
            # Update display
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.adjustSize()
            
            # Update comparison view if active
            if self.comparison_mode:
                self.update_comparison_view()
            
            # Update status bar
            self._update_status_bar()
            
        except Exception as e:
            print(f"Error updating image display: {e}")
            self.status_bar.showMessage(self.tr("Error displaying image"))

    def _update_status_bar(self):
        """Update the status bar with current image information"""
        if self.pixmap.isNull():
            self.status_bar.showMessage(self.tr("No image loaded"))
            return
        
        img_name = os.path.basename(self.current_image_path) if self.current_image_path else self.tr("Unsaved Image")
        
        # Add modification indicators
        mods = []
        if self.image_modified_by_bg_removal:
            mods.append(self.tr("no bg"))
        if self.image_modified_by_crop:
            mods.append(self.tr("cropped"))
        
        if mods:
            img_name += f" ({', '.join(mods)})"
            
        # Add modified indicator
        has_unsaved_changes = (
            self.rotation_angle != 0 or 
            self.image_modified_by_bg_removal or 
            self.image_modified_by_crop
        )
        
        modified_indicator = "*" if has_unsaved_changes else ""
        
        # Compose status message
        status_msg = (
            f"{modified_indicator}{img_name} | "
            f"{self.pixmap.width()}x{self.pixmap.height()} | "
            f"{self.tr('Zoom')}: {self.scale_factor*100:.0f}% | "
            f"{self.tr('Rotation')}: {self.rotation_angle}°"
        )
        
        # Add slideshow info if active
        if self.is_slideshow_active:
            status_msg += f" | {self.tr('Slideshow')}: {self.slideshow_interval/1000:.1f}s"
        
        self.status_bar.showMessage(status_msg)

    def _navigate_image(self, direction):
        """Navigate to next/previous image in directory"""
        if not self.image_files_in_directory:
            self.status_bar.showMessage(self.tr("No image files in directory"), 2000)
            return False
            
        num_files = len(self.image_files_in_directory)
        if num_files <= 1:  # No navigation if 0 or 1 image
            self.status_bar.showMessage(self.tr("No other images in this directory"), 2000)
            return False
            
        # Check for unsaved changes
        has_unsaved_changes = (
            self.rotation_angle != 0 or 
            self.image_modified_by_bg_removal or 
            self.image_modified_by_crop
        )
        
        if has_unsaved_changes:
            filename = os.path.basename(self.current_image_path) if self.current_image_path else self.tr("untitled image")
            reply = QMessageBox.question(
                self, 
                self.tr("Unsaved Changes"), 
                self.tr("Image '%s' has unsaved changes. Save before navigating?") % filename,
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                if not self.save_image():
                    return False  # Stop navigation if save fails or is cancelled
            elif reply == QMessageBox.Cancel:
                return False
                
        # Navigation logic
        next_index = (self.current_image_index + direction) % num_files
        
        # Try to load the next file
        for _ in range(num_files):
            file_to_try = self.image_files_in_directory[next_index]
            if self.load_image(file_to_try):
                return True
            else:
                self.status_bar.showMessage(
                    self.tr("Skipping unreadable file: %s") % os.path.basename(file_to_try), 2000)
                next_index = (next_index + direction) % num_files

        self.status_bar.showMessage(self.tr("No other readable images found"), 3000)
        return False

    def go_to_image(self, index):
        """Navigate to a specific image index"""
        if not self.image_files_in_directory:
            return
            
        if index < 0:  # Handle negative indices (like -1 for last)
            index = len(self.image_files_in_directory) + index
            
        if 0 <= index < len(self.image_files_in_directory):
            self.load_image(self.image_files_in_directory[index])

    def open_image_dialog(self):
        """Show open file dialog"""
        settings = QSettings()
        last_dir = settings.value("last_opened_directory", QDir.homePath())
        
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Open Image"),
            last_dir,
            self._get_supported_image_formats_filter()
        )
        
        if file_name:
            chosen_dir = QFileInfo(file_name).absolutePath()
            settings.setValue("last_opened_directory", chosen_dir)
            
            if not self.load_image(file_name):
                self.current_image_path = None
                self.current_image_index = -1
                self.image_files_in_directory = []
                self.update_actions_state()

    def _get_supported_image_formats_filter(self):
        """Get file filter string for supported image formats"""
        formats = QImageReader.supportedImageFormats()
        common_formats = "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"
        all_supported = " ".join([f"*.{bytes(fmt).decode()}" for fmt in formats])
        return (
            f"{self.tr('Common Image Files')} ({common_formats});;"
            f"{self.tr('All Supported Files')} ({all_supported});;"
            f"{self.tr('All Files')} (*)"
        )

    def save_image(self):
        """Save current image to its original file"""
        if self.pixmap.isNull():
            self.status_bar.showMessage(self.tr("No image to save"), 2000)
            return False
            
        # If there's no path, or it was modified in a way that suggests a new format (like bg removal), use Save As
        if not self.current_image_path or self.image_modified_by_bg_removal:
            return self.save_image_as()
            
        file_to_save = self.current_image_path
        
        # Apply current rotation to pixmap
        pixmap_to_save = self.pixmap
        if self.rotation_angle != 0:
            transform = QTransform()
            transform.rotate(self.rotation_angle)
            pixmap_to_save = pixmap_to_save.transformed(transform, Qt.SmoothTransformation)
        
        # Save directly without merging background
        if pixmap_to_save.save(file_to_save):
            self.status_bar.showMessage(self.tr("Image saved to %s") % file_to_save, 3000)
            # Reset state and reload to reflect saved state
            self.rotation_angle = 0
            self.image_modified_by_crop = False  # Crop is already applied to self.pixmap
            self.load_image(file_to_save) 
            self.imageSaved.emit(file_to_save)
            return True
        else:
            self.status_bar.showMessage(self.tr("Failed to save to %s") % file_to_save, 3000)
            QMessageBox.warning(self, self.tr("Save Error"), self.tr("Could not save image to %s") % file_to_save)
            return False

    def save_image_as(self):
        """Save current image to a new file"""
        if self.pixmap.isNull():
            return False
            
        base_path = self.current_image_path or QSettings().value(
            "last_opened_directory", QDir.homePath())
        
        file_name, selected_filter = self._get_save_filename(self.tr("Save Image As"), base_path)
        if not file_name:
            return False
            
        # Determine format from extension
        ext = os.path.splitext(file_name)[1].lower()
        format_map = {
            '.png': 'PNG',
            '.jpg': 'JPEG',
            '.jpeg': 'JPEG',
            '.bmp': 'BMP',
            '.tif': 'TIFF',
            '.tiff': 'TIFF'
        }
        file_format = format_map.get(ext, 'PNG')
        
        # Apply transformations
        pixmap_to_save = self.pixmap
        if self.rotation_angle != 0:
            transform = QTransform()
            transform.rotate(self.rotation_angle)
            pixmap_to_save = pixmap_to_save.transformed(transform, Qt.SmoothTransformation)
            
        if pixmap_to_save.save(file_name, file_format):
            self.status_bar.showMessage(self.tr("Image saved to %s") % file_name, 3000)
            # After saving as, the new file becomes the current one
            self.load_image(file_name) 
            self.imageSaved.emit(file_name)
            return True
        else:
            self.status_bar.showMessage(self.tr("Failed to save to %s") % file_name, 3000)
            QMessageBox.warning(self, self.tr("Save Error"), self.tr("Could not save image to %s") % file_name)
            return False

    def _get_save_filename(self, purpose, base_path):
        """Get filename for saving with appropriate defaults"""
        if base_path and os.path.isfile(base_path):
            original_dir = os.path.dirname(base_path)
            original_basename, original_ext = os.path.splitext(os.path.basename(base_path))
        else:
            original_dir = base_path if os.path.isdir(base_path) else QDir.homePath()
            original_basename = "untitled"
            original_ext = ".png"  # Default to png for new files
        
        suffix_mod = ""
        if self.rotation_angle != 0:
            suffix_mod += "_rotated"
        if self.image_modified_by_crop:
            suffix_mod += "_cropped"
        if self.image_modified_by_bg_removal:
            suffix_mod += "_no_bg"
            original_ext = ".png"  # Force PNG for transparency
            
        default_name = f"{original_basename}{suffix_mod}{original_ext}"
        default_path = os.path.join(original_dir, default_name)
        
        filters = (
            f"{self.tr('PNG Files')} (*.png);;"
            f"{self.tr('JPEG Files')} (*.jpg *.jpeg);;"
            f"{self.tr('BMP Files')} (*.bmp);;"
            f"{self.tr('TIFF Files')} (*.tif *.tiff);;"
            f"{self.tr('All Files')} (*)"
        )
        
        return QFileDialog.getSaveFileName(self, purpose, default_path, filters)

    def next_image_manual(self):
        """Navigate to next image"""
        self._navigate_image(direction=1)

    def prev_image_manual(self):
        """Navigate to previous image"""
        self._navigate_image(direction=-1)

    def zoom_in(self):
        """Zoom in on image"""
        if not self.pixmap.isNull():
            self.scale_image(1.25)

    def zoom_out(self):
        """Zoom out from image"""
        if not self.pixmap.isNull():
            self.scale_image(0.8)

    def scale_image(self, factor):
        """Scale the image by a factor."""
        self.scale_factor *= factor
        self.update_image_display()

    def fit_to_window(self):
        """Scale image to fit the scroll area."""
        if self.pixmap.isNull():
            return

        area_size = self.scroll_area.size()
        pixmap_size = self.pixmap.size()
        
        # Consider rotation when fitting
        if self.rotation_angle % 180 != 0:
            pixmap_size.transpose()

        if pixmap_size.width() == 0 or pixmap_size.height() == 0:
            return

        w_ratio = area_size.width() / pixmap_size.width()
        h_ratio = area_size.height() / pixmap_size.height()
        
        self.scale_factor = min(w_ratio, h_ratio)
        self.update_image_display()

    def actual_size(self):
        """Display image at its actual size (100% zoom)."""
        self.scale_factor = 1.0
        self.update_image_display()
        
    def rotate_left(self):
        """Rotate image 90 degrees counter-clockwise."""
        self.rotation_angle = (self.rotation_angle - 90) % 360
        self.update_image_display()

    def rotate_right(self):
        """Rotate image 90 degrees clockwise."""
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.update_image_display()

    def toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self.is_fullscreen:
            self.showNormal()
            self.toolbar.show()
        else:
            self.showFullScreen()
            self.toolbar.hide()
        self.is_fullscreen = not self.is_fullscreen
        self.fullscreen_action.setChecked(self.is_fullscreen)

    def show_change_background_color_dialog(self):
        """Show color dialog to change background color."""
        new_color = QColorDialog.getColor(self.viewer_bg_color, self, self.tr("Select Background Color"))
        if new_color.isValid():
            self.apply_background_color(new_color)
            # Save setting
            settings = QSettings()
            settings.setValue("viewer_background_color", new_color.name())

    def apply_background_color(self, color):
        """Apply a new background color to the viewer."""
        self.viewer_bg_color = color
        palette = self.scroll_area.palette()
        palette.setColor(QPalette.Window, color)
        self.scroll_area.setPalette(palette)
        self.scroll_area.setAutoFillBackground(True)

    def show_image_properties(self):
        """Show a dialog with image properties."""
        if self.pixmap.isNull():
            QMessageBox.information(self, self.tr("Properties"), self.tr("No image loaded."))
            return

        info = QFileInfo(self.current_image_path)
        
        # Basic properties
        properties = [
            f"<b>{self.tr('File')}:</b> {info.fileName()}",
            f"<b>{self.tr('Path')}:</b> {info.absoluteFilePath()}",
            f"<b>{self.tr('Size')}:</b> {self.pixmap.width()} x {self.pixmap.height()} {self.tr('pixels')}",
            f"<b>{self.tr('File Size')}:</b> {info.size() / 1024:.2f} KB",
            f"<b>{self.tr('Created')}:</b> {info.birthTime().toString(Qt.DefaultLocaleLongDate)}",
            f"<b>{self.tr('Modified')}:</b> {info.lastModified().toString(Qt.DefaultLocaleLongDate)}",
            f"<b>{self.tr('Depth')}:</b> {self.pixmap.depth()}-bit",
        ]
        
        # Add EXIF metadata if available
        if PILLOW_AVAILABLE and self.current_image_path:
            try:
                with Image.open(self.current_image_path) as img:
                    exif_data = img._getexif()
                    if exif_data:
                        properties.append("<br><b>EXIF Metadata:</b>")
                        for tag, value in exif_data.items():
                            tag_name = ExifTags.TAGS.get(tag, tag)
                            properties.append(f"&nbsp;&nbsp;{tag_name}: {value}")
            except Exception as e:
                print(f"Error reading EXIF data: {e}")
        
        # Create a scrollable dialog for properties
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Image Properties"))
        dialog.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextDocument()
        text_edit.setHtml("<br>".join(properties))
        
        scroll_area = QScrollArea()
        content = QLabel()
        content.setTextFormat(Qt.RichText)
        content.setText(text_edit.toHtml())
        content.setWordWrap(True)
        content.setMargin(10)
        
        scroll_area.setWidget(content)
        scroll_area.setWidgetResizable(True)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        
        layout.addWidget(scroll_area)
        layout.addWidget(button_box)
        
        dialog.exec()

    def copy_image_to_clipboard(self):
        """Copy the currently displayed image to the system clipboard."""
        if not self.pixmap.isNull():
            QApplication.clipboard().setPixmap(self.image_label.pixmap())
            self.status_bar.showMessage(self.tr("Image copied to clipboard"), 2000)

    def delete_current_image(self):
        """Delete the current image file (moves to trash if available)."""
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            self.status_bar.showMessage(self.tr("No file to delete"), 2000)
            return

        file_name = os.path.basename(self.current_image_path)
        reply = QMessageBox.question(
            self, self.tr("Confirm Delete"),
            self.tr("Are you sure you want to delete '%s'?") % file_name,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            path_to_delete = self.current_image_path
            
            # Try to navigate away first
            if self._navigate_image(1) or self._navigate_image(-1):
                # Navigation successful, now delete
                try:
                    if SEND2TRASH_AVAILABLE:
                        send2trash.send2trash(path_to_delete)
                        self.status_bar.showMessage(self.tr("Moved '%s' to trash") % file_name, 3000)
                    else:
                        os.remove(path_to_delete)
                        self.status_bar.showMessage(self.tr("Permanently deleted '%s'") % file_name, 3000)
                    self.load_directory_images(self.current_image_path)  # Refresh file list
                except Exception as e:
                    QMessageBox.warning(self, self.tr("Delete Error"), self.tr("Could not delete file: %s") % e)
                    self.load_image(path_to_delete)  # Reload if delete failed
            else:
                # Could not navigate away, so clear the view after delete
                try:
                    if SEND2TRASH_AVAILABLE:
                        send2trash.send2trash(path_to_delete)
                    else:
                        os.remove(path_to_delete)
                    self.pixmap = QPixmap()
                    self.current_image_path = None
                    self.image_files_in_directory = []
                    self.update_image_display()
                    self.update_actions_state()
                except Exception as e:
                    QMessageBox.warning(self, self.tr("Delete Error"), self.tr("Could not delete file: %s") % e)

    def process_remove_background(self):
        """Handle the background removal process."""
        if self.pixmap.isNull() or not REQUESTS_AVAILABLE:
            return

        if not self.remove_bg_api_key:
            QMessageBox.information(self, self.tr("API Key Required"), 
                                    self.tr("Please set your remove.bg API key in Settings -> Set API Key..."))
            return

        # Show progress
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_bar.showMessage(self.tr("Removing background, please wait..."))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Disable relevant actions during processing
        self.remove_bg_action.setEnabled(False)
        self.save_action.setEnabled(False)
        self.save_as_action.setEnabled(False)

        # Create and start worker thread
        self.bg_removal_worker = RemoveBgWorker(self.current_image_path, self.remove_bg_api_key)
        self.bg_removal_worker.signals.result.connect(self._handle_bg_removal_result)
        self.bg_removal_worker.signals.error.connect(self._handle_bg_removal_error)
        self.bg_removal_worker.signals.finished.connect(self._handle_bg_removal_finished)
        self.bg_removal_worker.signals.progress.connect(self.progress_bar.setValue)
        self.bg_removal_worker.start()

    def _handle_bg_removal_result(self, image_data):
        """Handle successful background removal result"""
        new_pixmap = QPixmap()
        if new_pixmap.loadFromData(image_data):
            self.pixmap = new_pixmap
            self.image_modified_by_bg_removal = True
            self.rotation_angle = 0  # Reset rotation
            self.update_image_display()
            self.status_bar.showMessage(self.tr("Background removed successfully. Save the new image."), 5000)
            self.backgroundRemoved.emit()
        else:
            raise ValueError(self.tr("Failed to load image from API response."))

    def _handle_bg_removal_error(self, error_msg):
        """Handle background removal error"""
        QMessageBox.critical(self, self.tr("API Error"), 
                            self.tr("Background removal failed: %s") % error_msg)
        self.status_bar.showMessage(self.tr("Background removal failed."), 5000)

    def _handle_bg_removal_finished(self):
        """Clean up after background removal completes"""
        self.progress_bar.hide()
        QApplication.restoreOverrideCursor()
        self.remove_bg_action.setEnabled(True)
        self.save_action.setEnabled(True)
        self.save_as_action.setEnabled(True)
        self.update_actions_state()

    def show_set_api_key_dialog(self):
        """Show dialog to set the remove.bg API key."""
        dialog = ApiKeyDialog(self.remove_bg_api_key, self)
        if dialog.exec() == QDialog.Accepted:
            self._save_api_key(dialog.get_api_key())
            self.status_bar.showMessage(self.tr("API Key saved."), 2000)

    def _save_api_key(self, api_key):
        """Save API key to persistent settings"""
        settings = QSettings()
        settings.setValue("remove_bg_api_key", api_key)
        self.remove_bg_api_key = api_key
        self.update_actions_state()

    def toggle_crop_mode(self, checked):
        """Toggle cropping mode on or off."""
        self.is_cropping = checked
        if self.is_cropping:
            self.setCursor(Qt.CrossCursor)
            self.crop_overlay.setGeometry(self.image_label.rect())
            self.crop_overlay.show()
            self.crop_overlay.set_ratio(self.current_crop_ratio)
            self.crop_overlay.set_crop_rect(QRect())
            self.crop_overlay.setFocus()
            self.apply_crop_action.setEnabled(False)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.crop_overlay.hide()
            self.apply_crop_action.setEnabled(False)
        self.update_actions_state()

    def set_crop_ratio(self, ratio):
        """Set the aspect ratio for cropping."""
        self.current_crop_ratio = ratio
        self.crop_overlay.set_ratio(ratio)
        
        # Update checked state in ratio group
        if ratio is None:
            self.crop_free_action.setChecked(True)
        elif ratio == (1, 1):
            self.crop_1_1_action.setChecked(True)
        elif ratio == (4, 3):
            self.crop_4_3_action.setChecked(True)
        elif ratio == (3, 2):
            self.crop_3_2_action.setChecked(True)
        elif ratio == (16, 9):
            self.crop_16_9_action.setChecked(True)

    def show_custom_ratio_dialog(self):
        """Show dialog to set a custom crop ratio."""
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Custom Crop Ratio"))
        
        layout = QFormLayout(dialog)
        
        width_spin = QSpinBox()
        width_spin.setRange(1, 100)
        width_spin.setValue(4)
        
        height_spin = QSpinBox()
        height_spin.setRange(1, 100)
        height_spin.setValue(3)
        
        layout.addRow(self.tr("Width:"), width_spin)
        layout.addRow(self.tr("Height:"), height_spin)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)
        
        if dialog.exec() == QDialog.Accepted:
            self.set_crop_ratio((width_spin.value(), height_spin.value()))

    def eventFilter(self, source, event):
        """Filter events for mouse interaction on the image label for cropping."""
        if source is self.image_label and self.is_cropping:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.crop_origin_point_on_label = event.pos()
                self.crop_overlay.set_crop_rect(QRect(self.crop_origin_point_on_label, QSize()))
                self.crop_overlay.show()
                self.crop_overlay.setFocus()
                self.apply_crop_action.setEnabled(False)
                return True
            elif event.type() == QEvent.MouseMove and self.crop_origin_point_on_label:
                current_pos = event.pos()
                rect = QRect(self.crop_origin_point_on_label, current_pos).normalized()
                if self.current_crop_ratio:
                    w_ratio, h_ratio = self.current_crop_ratio
                    width = rect.width()
                    height = int(width * h_ratio / w_ratio)
                    rect.setHeight(height)
                self.crop_overlay.set_crop_rect(rect)
                self.apply_crop_action.setEnabled(rect.width() > 10 and rect.height() > 10)
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.crop_origin_point_on_label = None
                self.apply_crop_action.setEnabled(not self.crop_overlay.crop_rect.isNull())
                return True
        return super().eventFilter(source, event)

    def apply_crop_from_selection(self):
        """Apply the crop based on the overlay selection."""
        if self.pixmap.isNull():
            return
            
        crop_rect = self.crop_overlay.crop_rect
        if crop_rect.isNull() or crop_rect.width() < 10 or crop_rect.height() < 10:
            return

        label_pixmap = self.image_label.pixmap()
        if label_pixmap.isNull():
            return

        # Calculate the position of the pixmap within the label
        label_w, label_h = self.image_label.width(), self.image_label.height()
        pixmap_w, pixmap_h = label_pixmap.width(), label_pixmap.height()
        offset_x = (label_w - pixmap_w) // 2
        offset_y = (label_h - pixmap_h) // 2

        # Convert crop selection from label coordinates to pixmap coordinates
        selection_on_pixmap = crop_rect.translated(-offset_x, -offset_y)
        
        # Calculate scale factor between original image and displayed pixmap
        scale = self.pixmap.width() / (label_pixmap.width() / self.scale_factor)
        
        # Convert to original image coordinates
        crop_rect_on_original = QRect(
            int(selection_on_pixmap.x() * scale),
            int(selection_on_pixmap.y() * scale),
            int(selection_on_pixmap.width() * scale),
            int(selection_on_pixmap.height() * scale)
        )

        # Perform the crop
        cropped_pixmap = self.pixmap.copy(crop_rect_on_original)
        if not cropped_pixmap.isNull():
            self.pixmap = cropped_pixmap
            self.image_modified_by_crop = True
            self.toggle_crop_mode(False)
            self.crop_mode_action.setChecked(False)
            self.fit_to_window()
            self.update_actions_state()

    def toggle_comparison_mode(self, checked):
        """Toggle before/after comparison mode."""
        self.comparison_mode = checked
        self.compare_action.setChecked(checked)
        
        if checked:
            # Setup comparison view
            self.scroll_area.takeWidget()
            self.scroll_area.setWidget(self.comparison_container)
            self.comparison_label.show()
            self.comparison_slider.show()
            self.update_comparison_view()
        else:
            # Restore normal view
            self.scroll_area.takeWidget()
            self.scroll_area.setWidget(self.image_label)
            self.comparison_label.hide()
            self.comparison_slider.hide()
        
        self.update_actions_state()

    def update_comparison_view(self):
        """Update the comparison view based on slider position."""
        if not self.comparison_mode or self.pixmap.isNull():
            return
            
        # Get current displayed pixmap (with transformations)
        current_pixmap = self.image_label.pixmap()
        if current_pixmap.isNull():
            return
            
        # Get original pixmap (with same transformations)
        transform = QTransform()
        transform.rotate(self.rotation_angle)
        original_pixmap = self.original_pixmap.transformed(transform, Qt.SmoothTransformation)
        original_pixmap = original_pixmap.scaled(
            current_pixmap.width(), current_pixmap.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        
        # Calculate split position
        split_pos = self.comparison_slider.value() / 100.0
        split_x = int(current_pixmap.width() * split_pos)
        
        # Create comparison image
        comparison_pixmap = QPixmap(current_pixmap.size())
        comparison_pixmap.fill(Qt.transparent)
        
        painter = QPainter(comparison_pixmap)
        painter.drawPixmap(0, 0, original_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(split_x, 0, 
                         current_pixmap.copy(split_x, 0, 
                                           current_pixmap.width() - split_x, 
                                           current_pixmap.height()))
        painter.end()
        
        # Update labels
        self.image_label.setPixmap(original_pixmap)
        self.comparison_label.setPixmap(comparison_pixmap)
        
        # Update slider tooltip
        self.comparison_slider.setToolTip(self.tr("Comparison: %d%%") % int(split_pos * 100))

    def start_slideshow(self):
        """Start slideshow of images in current directory."""
        if len(self.image_files_in_directory) < 2:
            QMessageBox.information(self, self.tr("Slideshow"), 
                                  self.tr("Need at least 2 images in folder for slideshow."))
            return
            
        self.is_slideshow_active = True
        self.slideshow_timer.start(self.slideshow_interval)
        self.slideshow_start_action.setEnabled(False)
        self.slideshow_stop_action.setEnabled(True)
        self.status_bar.showMessage(self.tr("Slideshow started - press Esc to stop"))
        self.update_actions_state()

    def stop_slideshow(self):
        """Stop the running slideshow."""
        self.is_slideshow_active = False
        self.slideshow_timer.stop()
        self.slideshow_start_action.setEnabled(True)
        self.slideshow_stop_action.setEnabled(False)
        self.status_bar.showMessage(self.tr("Slideshow stopped"))
        self.update_actions_state()

    def show_slideshow_settings(self):
        """Show slideshow settings dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Slideshow Settings"))
        
        layout = QFormLayout(dialog)
        
        interval_spin = QSpinBox()
        interval_spin.setRange(1, 60)
        interval_spin.setValue(self.slideshow_interval // 1000)
        interval_spin.setSuffix(self.tr(" seconds"))
        
        layout.addRow(self.tr("Slide interval:"), interval_spin)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)
        
        if dialog.exec() == QDialog.Accepted:
            self.slideshow_interval = interval_spin.value() * 1000
            if self.is_slideshow_active:
                self.slideshow_timer.start(self.slideshow_interval)

    def _add_to_recent_files(self, file_path):
        """Add a file to the recent files list."""
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
            
        self.recent_files.insert(0, file_path)
        
        # Trim to max recent files
        if len(self.recent_files) > self.max_recent_files:
            self.recent_files = self.recent_files[:self.max_recent_files]
            
        self.update_recent_files_menu()
        
        # Save to settings
        settings = QSettings()
        settings.setValue("recent_files", self.recent_files)

    def update_recent_files_menu(self):
        """Update the recent files menu with current files."""
        self.recent_menu.clear()
        
        if not self.recent_files:
            action = QAction(self.tr("No recent files"), self)
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return
            
        for i, file_path in enumerate(self.recent_files):
            if i < 9:  # Add keyboard shortcut for first 9 items
                text = f"&{i+1} {os.path.basename(file_path)}"
            else:
                text = os.path.basename(file_path)
                
            action = QAction(text, self)
            action.setData(file_path)
            action.triggered.connect(lambda checked, path=file_path: self._open_recent_file(path))
            self.recent_menu.addAction(action)
        
        self.recent_menu.addSeparator()
        self.recent_menu.addAction(self.clear_recent_action)

    def _open_recent_file(self, file_path=None):
        """Open a file from the recent files list."""
        if file_path is None:
            action = self.sender()
            if action:
                file_path = action.data()
                
        if file_path and os.path.exists(file_path):
            self.load_image(file_path)
        else:
            QMessageBox.warning(self, self.tr("File Not Found"), 
                              self.tr("The file '%s' no longer exists.") % file_path)
            self.recent_files.remove(file_path)
            self.update_recent_files_menu()

    def clear_recent_files(self):
        """Clear the recent files list."""
        self.recent_files = []
        self.update_recent_files_menu()
        
        # Save to settings
        settings = QSettings()
        settings.setValue("recent_files", self.recent_files)

    def load_language(self, language_code):
        """Load translation for the specified language."""
        if language_code == "en":
            QApplication.removeTranslator(self.translator)
            self.current_language = "en"
        else:
            if self.translator.load(f":/translations/imageviewer_{language_code}.qm"):
                QApplication.installTranslator(self.translator)
                self.current_language = language_code
            else:
                print(f"Failed to load translation for {language_code}")
                self.current_language = "en"
        
        # Retranslate UI
        self.retranslateUi()

    def set_language(self, language_code):
        """Set application language."""
        if language_code != self.current_language:
            self.load_language(language_code)
            settings = QSettings()
            settings.setValue("language", language_code)

    def retranslateUi(self):
        """Retranslate the UI after language change."""
        # Window title
        self.setWindowTitle(f"{self.APPLICATION} {self.VERSION}")
        if self.current_image_path:
            self.setWindowTitle(f"{os.path.basename(self.current_image_path)} - {self.APPLICATION}")
        
        # Retranslate all actions
        self.open_action.setText(self.tr("&Open..."))
        self.save_action.setText(self.tr("&Save"))
        self.save_as_action.setText(self.tr("Save &As..."))
        self.exit_action.setText(self.tr("&Exit"))
        self.copy_action.setText(self.tr("&Copy Image"))
        self.remove_bg_action.setText(self.tr("Remove &Background"))
        self.delete_action.setText(self.tr("&Delete Image"))
        self.compare_action.setText(self.tr("Compare"))
        self.zoom_in_action.setText(self.tr("Zoom &In"))
        self.zoom_out_action.setText(self.tr("Zoom &Out"))
        self.fit_window_action.setText(self.tr("&Fit to Window"))
        self.actual_size_action.setText(self.tr("&Actual Size"))
        self.rotate_left_action.setText(self.tr("Rotate &Left"))
        self.rotate_right_action.setText(self.tr("Rotate &Right"))
        self.fullscreen_action.setText(self.tr("&Fullscreen"))
        self.change_bg_color_action.setText(self.tr("Change &Background Color..."))
        self.properties_action.setText(self.tr("Image &Properties..."))
        self.prev_action.setText(self.tr("&Previous Image"))
        self.next_action.setText(self.tr("&Next Image"))
        self.first_action.setText(self.tr("&First Image"))
        self.last_action.setText(self.tr("&Last Image"))
        self.set_api_key_action.setText(self.tr("Set API &Key..."))
        self.crop_mode_action.setText(self.tr("&Crop Mode"))
        self.crop_free_action.setText(self.tr("&Free Crop"))
        self.crop_1_1_action.setText(self.tr("Crop &1:1 (Square)"))
        self.crop_4_3_action.setText(self.tr("Crop &4:3"))
        self.crop_3_2_action.setText(self.tr("Crop &3:2"))
        self.crop_16_9_action.setText(self.tr("Crop &16:9"))
        self.crop_custom_action.setText(self.tr("&Custom Ratio..."))
        self.crop_show_grid_action.setText(self.tr("Show &Grid"))
        self.crop_show_guides_action.setText(self.tr("Show &Guides"))
        self.apply_crop_action.setText(self.tr("&Apply Crop"))
        self.slideshow_start_action.setText(self.tr("Start &Slideshow"))
        self.slideshow_stop_action.setText(self.tr("Stop Slideshow"))
        self.slideshow_settings_action.setText(self.tr("Slideshow &Settings..."))
        self.help_action.setText(self.tr("&Help"))
        self.about_action.setText(self.tr("&About"))
        self.about_qt_action.setText(self.tr("About &Qt"))
        self.clear_recent_action.setText(self.tr("Clear Recent Files"))
        
        # Update status bar
        self._update_status_bar()

    def show_help(self):
        """Show application help."""
        help_text = f"""
        <h1>{self.APPLICATION} {self.VERSION}</h1>
        <h2>{self.tr('Keyboard Shortcuts')}</h2>
        <ul>
            <li><b>{self.tr('Navigation')}:</b> {self.tr('Left/Right arrows')} - {self.tr('Previous/Next image')}</li>
            <li><b>{self.tr('Zoom')}:</b> +/- {self.tr('or')} Ctrl+MouseWheel - {self.tr('Zoom in/out')}</li>
            <li><b>F</b> - {self.tr('Fit to window')}</li>
            <li><b>Ctrl+0</b> - {self.tr('Actual size')}</li>
            <li><b>Ctrl+L/R</b> - {self.tr('Rotate left/right')}</li>
            <li><b>F11</b> - {self.tr('Toggle fullscreen')}</li>
            <li><b>Ctrl+B</b> - {self.tr('Remove background')}</li>
            <li><b>Ctrl+Shift+C</b> - {self.tr('Toggle crop mode')}</li>
            <b>Ctrl+C</b> - {self.tr('Toggle comparison mode')}</li>
            <li><b>Ctrl+Shift+S</b> - {self.tr('Start slideshow')}</li>
            <li><b>Esc</b> - {self.tr('Stop slideshow')}</li>
        </ul>
        """
        
        help_dialog = QDialog(self)
        help_dialog.setWindowTitle(self.tr("Help"))
        help_dialog.resize(500, 400)
        
        layout = QVBoxLayout(help_dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(help_text)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(help_dialog.accept)
        
        layout.addWidget(text_edit)
        layout.addWidget(button_box)
        
        help_dialog.exec()

    def show_about(self):
        """Show about dialog."""
        about_text = f"""
        <h1>{self.APPLICATION}</h1>
        <p>{self.tr('Version')}: {self.VERSION}</p>
        <p>{self.tr('A professional image viewer with advanced features including:')}</p>
        <ul>
            <li>{self.tr('High-quality image display with zoom and rotation')}</li>
            <li>{self.tr('Advanced cropping tools with aspect ratio locking')}</li>
            <li>{self.tr('Background removal integration')}</li>
            <li>{self.tr('Image comparison mode')}</li>
            <li>{self.tr('Slideshow functionality')}</li>
        </ul>
        <p>{self.tr('Developed by Merdekasoft')}</p>
        <p>{self.tr('Built with PySide6 and Qt')}</p>
        """
        
        QMessageBox.about(self, self.tr("About"), about_text)

    def update_actions_state(self):
        """Update enabled/disabled state of actions based on current context."""
        has_image = not self.pixmap.isNull()
        has_multiple_images = len(self.image_files_in_directory) > 1
        has_recent_files = len(self.recent_files) > 0
        
        # File actions
        self.save_action.setEnabled(has_image)
        self.save_as_action.setEnabled(has_image)
        self.delete_action.setEnabled(has_image)
        self.properties_action.setEnabled(has_image)
        
        # Edit actions
        self.copy_action.setEnabled(has_image)
        self.remove_bg_action.setEnabled(has_image and REQUESTS_AVAILABLE and bool(self.remove_bg_api_key))
        self.compare_action.setEnabled(has_image and 
                                     (self.image_modified_by_bg_removal or 
                                      self.image_modified_by_crop or 
                                      self.rotation_angle != 0))
        
        # View actions
        self.zoom_in_action.setEnabled(has_image)
        self.zoom_out_action.setEnabled(has_image)
        self.fit_window_action.setEnabled(has_image)
        self.actual_size_action.setEnabled(has_image)
        self.rotate_left_action.setEnabled(has_image)
        self.rotate_right_action.setEnabled(has_image)
        self.change_bg_color_action.setEnabled(True)
        
        # Navigate actions
        self.prev_action.setEnabled(has_image and has_multiple_images)
        self.next_action.setEnabled(has_image and has_multiple_images)
        self.first_action.setEnabled(has_image and has_multiple_images)
        self.last_action.setEnabled(has_image and has_multiple_images)
        
        # Slideshow actions
        self.slideshow_start_action.setEnabled(has_image and has_multiple_images)
        self.slideshow_stop_action.setEnabled(self.is_slideshow_active)
        
        # Crop actions
        self.crop_mode_action.setEnabled(has_image)
        self.apply_crop_action.setEnabled(has_image and self.is_cropping and 
                                        not self.crop_overlay.crop_rect.isNull())
        
        # Recent files menu
        self.clear_recent_action.setEnabled(has_recent_files)

    def resizeEvent(self, event):
        """Handle window resize event to refit image if necessary."""
        super().resizeEvent(event)
        self.fit_to_window()
        if self.is_cropping:
            self.crop_overlay.setGeometry(self.image_label.rect())

    def closeEvent(self, event):
        """Handle window close event."""
        # Stop slideshow if running
        if self.is_slideshow_active:
            self.stop_slideshow()
            
        # Check for unsaved changes
        has_unsaved_changes = (
            self.rotation_angle != 0 or 
            self.image_modified_by_bg_removal or 
            self.image_modified_by_crop
        )
        
        if has_unsaved_changes and self.current_image_path:
            filename = os.path.basename(self.current_image_path)
            reply = QMessageBox.question(
                self, 
                self.tr("Unsaved Changes"), 
                self.tr("Image '%s' has unsaved changes. Save before closing?") % filename,
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                if not self.save_image():
                    event.ignore()
                    return
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
                
        # Save settings
        self._save_settings()
        event.accept()

    def _on_image_loaded(self, file_path):
        """Handle image loaded signal."""
        pass  # Could add logging or other side effects here

    def _on_image_saved(self, file_path):
        """Handle image saved signal."""
        pass  # Could add logging or other side effects here

    def _on_background_removed(self):
        """Handle background removed signal."""
        pass  # Could add logging or other side effects here


if __name__ == '__main__':
    # Create application instance
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    # Set application font
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    
    # Create and show main window
    image_to_open = sys.argv[1] if len(sys.argv) > 1 else None
    viewer = ImageViewer(image_path=image_to_open)
    viewer.show()
    
    # Start application event loop
    sys.exit(app.exec())
