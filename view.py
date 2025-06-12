#!/usr/bin/env python3
"""
Professional Image Viewer Application
Features:
- High-quality image display with zoom, rotation, and navigation
- Advanced cropping with aspect ratio locking
- Background removal integration with remove.bg API
- Professional UI with toolbar, menus, and status bar
- Comprehensive settings management
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QScrollArea, QSizePolicy, QFileDialog,
    QToolBar, QStatusBar, QToolButton, QFrame, QStyle,
    QMessageBox, QAction, QDialog, QFormLayout, QDialogButtonBox,
    QMenu, QLineEdit, QColorDialog, QRubberBand, QActionGroup
)
from PyQt5.QtGui import (
    QPixmap, QImageReader, QTransform, QIcon, QPalette, QKeySequence,
    QClipboard, QColor, QPainter, QImage
)
from PyQt5.QtCore import (
    Qt, QDir, QStandardPaths, QFile, QFileInfo, QSize, QSettings,
    QDateTime, QEvent, QRect, QPoint, QRectF
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


class ApiKeyDialog(QDialog):
    """Dialog for setting remove.bg API key"""
    def __init__(self, current_api_key="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("API Key Configuration")
        self.setWindowIcon(QIcon.fromTheme("preferences-system"))
        
        layout = QFormLayout(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setText(current_api_key)
        self.api_key_input.setPlaceholderText("Enter your remove.bg API key")
        
        layout.addRow("API Key:", self.api_key_input)
        
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        
        self.setMinimumWidth(400)

    def get_api_key(self):
        """Get the sanitized API key from dialog"""
        return self.api_key_input.text().strip()


class ImageViewer(QMainWindow):
    """Main application window for the Image Viewer"""
    
    VERSION = "1.2.0"
    ORGANIZATION = "DigitalVision"
    APPLICATION = "Professional Image Viewer"
    
    def __init__(self, image_path=None):
        super().__init__()
        
        # Initialize application state
        self.current_image_path = None
        self.current_image_index = -1
        self.image_files_in_directory = []
        self.scale_factor = 1.0
        self.rotation_angle = 0
        self.initial_image_to_load = image_path
        self.pixmap = QPixmap()
        self.is_fullscreen = False
        self.image_modified_by_bg_removal = False
        self.image_modified_by_crop = False
        self.remove_bg_api_key = ""
        self.viewer_bg_color = QColor(Qt.darkGray)
        
        # Crop-related state
        self.is_cropping = False
        self.rubber_band = None
        self.crop_origin_point_on_label = None
        self.current_selection_rect_on_label = None
        self.current_crop_ratio = None
        
        # Initialize UI and settings
        self._initialize_application()
        self._load_settings()
        self._setup_ui()
        
        # Load initial image if provided
        self._load_initial_image()

    def _initialize_application(self):
        """Set application metadata and organization"""
        QApplication.setOrganizationName(self.ORGANIZATION)
        QApplication.setApplicationName(self.APPLICATION)
        QApplication.setApplicationVersion(self.VERSION)
        QIcon.setThemeName("breeze")

    def _load_settings(self):
        """Load persistent application settings"""
        settings = QSettings()
        self.remove_bg_api_key = settings.value(
            "remove_bg_api_key", 
            "",
            type=str
        )
        
        default_bg_color = self.palette().color(QPalette.Window)
        if not default_bg_color.isValid():
            default_bg_color = QColor(Qt.lightGray)
            
        bg_color_name = settings.value(
            "viewer_background_color", 
            default_bg_color.name(),
            type=str
        )
        
        loaded_color = QColor(bg_color_name)
        self.viewer_bg_color = loaded_color if loaded_color.isValid() else default_bg_color

    def _save_api_key(self, api_key):
        """Save API key to persistent settings"""
        settings = QSettings()
        settings.setValue("remove_bg_api_key", api_key)
        self.remove_bg_api_key = api_key
        self.update_actions_state()

    def _setup_ui(self):
        """Initialize the main application UI"""
        self.setWindowTitle(f"{self.APPLICATION} {self.VERSION}")
        self.setGeometry(100, 100, 1024, 768)
        self.setMinimumSize(640, 480)
        
        # Central widget setup
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # Main layout
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Image display components
        self._setup_image_display()
        
        # Create actions, menus and toolbar
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Apply initial settings
        self.apply_background_color(self.viewer_bg_color)
        self.status_bar.showMessage("Ready")
        self.update_actions_state()
        self.setFocusPolicy(Qt.StrongFocus)

    def _setup_image_display(self):
        """Setup the image display components"""
        self.image_label = QLabel()
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setScaledContents(False)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.installEventFilter(self)
        
        self.scroll_area = QScrollArea(self) # Changed for simplicity, CustomScrollArea may not be defined
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(False)
        
        self.main_layout.addWidget(self.scroll_area)

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

    def _create_file_actions(self):
        """Create file-related actions"""
        self.open_action = self._create_action(
            "document-open", 
            "&Open...", 
            "Open an image file",
            QKeySequence.Open,
            self.open_image_dialog
        )
        
        self.save_action = self._create_action(
            "document-save", 
            "&Save", 
            "Save the current image",
            QKeySequence.Save,
            self.save_image
        )
        
        self.save_as_action = self._create_action(
            "document-save-as", 
            "Save &As...", 
            "Save the current image with a new name",
            QKeySequence.SaveAs,
            self.save_image_as
        )
        
        self.exit_action = self._create_action(
            "application-exit", 
            "&Exit", 
            "Exit the application",
            QKeySequence.Quit,
            self.close
        )

    def _create_edit_actions(self):
        """Create edit-related actions"""
        self.copy_action = self._create_action(
            "edit-copy", 
            "&Copy Image", 
            "Copy image to clipboard",
            QKeySequence.Copy,
            self.copy_image_to_clipboard
        )
        
        self.remove_bg_action = self._create_action(
            "edit-clear", 
            "Remove &Background", 
            "Remove image background using remove.bg",
            QKeySequence("Ctrl+B"),
            self.process_remove_background
        )
        
        self.delete_action = self._create_action(
            "edit-delete", 
            "&Delete Image", 
            "Move current image to trash",
            QKeySequence.Delete,
            self.delete_current_image
        )

    def _create_view_actions(self):
        """Create view-related actions"""
        self.zoom_in_action = self._create_action(
            "zoom-in", 
            "Zoom &In", 
            "Zoom in on the image",
            QKeySequence.ZoomIn,
            self.zoom_in
        )
        
        self.zoom_out_action = self._create_action(
            "zoom-out", 
            "Zoom &Out", 
            "Zoom out from the image",
            QKeySequence.ZoomOut,
            self.zoom_out
        )
        
        self.fit_window_action = self._create_action(
            "zoom-fit-best", 
            "&Fit to Window", 
            "Fit image to window size",
            QKeySequence("F"),
            self.fit_to_window
        )
        
        self.actual_size_action = self._create_action(
            "zoom-original", 
            "&Actual Size", 
            "View image at 100% scale",
            QKeySequence("Ctrl+0"),
            self.actual_size
        )
        
        self.rotate_left_action = self._create_action(
            "object-rotate-left", 
            "Rotate &Left", 
            "Rotate image 90° counter-clockwise",
            QKeySequence("Ctrl+L"),
            self.rotate_left
        )
        
        self.rotate_right_action = self._create_action(
            "object-rotate-right", 
            "Rotate &Right", 
            "Rotate image 90° clockwise",
            QKeySequence("Ctrl+R"),
            self.rotate_right
        )
        
        self.fullscreen_action = self._create_action(
            "view-fullscreen", 
            "&Fullscreen", 
            "Toggle fullscreen mode",
            QKeySequence("F11"),
            self.toggle_fullscreen
        )
        self.fullscreen_action.setCheckable(True)
        
        self.change_bg_color_action = self._create_action(
            "preferences-desktop-theme", 
            "Change &Background Color...", 
            "Change viewer background color",
            None,
            self.show_change_background_color_dialog
        )
        
        self.properties_action = self._create_action(
            "document-properties", 
            "Image &Properties...", 
            "Show image properties",
            QKeySequence("Alt+Return"),
            self.show_image_properties
        )

    def _create_navigate_actions(self):
        """Create navigation-related actions"""
        self.prev_action = self._create_action(
            "go-previous", 
            "&Previous Image", 
            "Go to previous image in folder",
            QKeySequence("Left"),
            self.prev_image_manual
        )
        
        self.next_action = self._create_action(
            "go-next", 
            "&Next Image", 
            "Go to next image in folder",
            QKeySequence("Right"),
            self.next_image_manual
        )

    def _create_settings_actions(self):
        """Create settings-related actions"""
        self.set_api_key_action = self._create_action(
            "configure", 
            "Set API &Key...", 
            "Set remove.bg API key",
            None,
            self.show_set_api_key_dialog
        )

    def _create_crop_actions(self):
        """Create crop-related actions"""
        self.crop_mode_action = self._create_action(
            "transform-crop", 
            "&Crop Mode", 
            "Toggle crop selection mode",
            None,
            self.toggle_crop_mode
        )
        self.crop_mode_action.setCheckable(True)
        
        # Crop ratio actions
        self.crop_free_action = QAction("&Free Crop", self)
        self.crop_free_action.setCheckable(True)
        self.crop_free_action.triggered.connect(lambda: self.set_crop_ratio(None))
        
        self.crop_2_3_action = QAction("Crop &2:3", self)
        self.crop_2_3_action.setCheckable(True)
        self.crop_2_3_action.triggered.connect(lambda: self.set_crop_ratio((2, 3)))
        
        self.crop_3_4_action = QAction("Crop &3:4", self)
        self.crop_3_4_action.setCheckable(True)
        self.crop_3_4_action.triggered.connect(lambda: self.set_crop_ratio((3, 4)))
        
        # Group for exclusive checking of crop ratio actions
        self.crop_ratio_group = QActionGroup(self)
        self.crop_ratio_group.addAction(self.crop_free_action)
        self.crop_ratio_group.addAction(self.crop_2_3_action)
        self.crop_ratio_group.addAction(self.crop_3_4_action)
        self.crop_ratio_group.setExclusive(True)
        self.crop_free_action.setChecked(True)  # Default to free crop
        
        self.apply_crop_action = self._create_action(
            "dialog-ok-apply", 
            "&Apply Crop", 
            "Apply the current crop selection",
            None,
            self.apply_crop_from_selection
        )
        self.apply_crop_action.setEnabled(False)

    def _create_action(self, icon_name, text, tooltip, shortcut, callback):
        """Helper to create standardized actions"""
        # A fallback for standard icons that might not be in the theme
        try:
            icon = QIcon.fromTheme(icon_name)
            if icon.isNull():
                 # Try to get a standard pixmap as a fallback
                 standard_icon_enum = getattr(QStyle, f"SP_{icon_name.replace('-', '_').title()}", None)
                 if standard_icon_enum:
                     icon = self.style().standardIcon(standard_icon_enum)
                 else: # final fallback to a generic icon
                     icon = QIcon.fromTheme("application-x-executable")
        except Exception:
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
        file_menu = menubar.addMenu('&File')
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.properties_action)
        file_menu.addSeparator()
        file_menu.addAction(self.delete_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu('&Edit')
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.remove_bg_action)
        edit_menu.addSeparator()
        
        # Crop submenu
        crop_menu = edit_menu.addMenu("&Crop")
        crop_menu.addAction(self.crop_mode_action)
        crop_menu.addSeparator()
        crop_menu.addAction(self.crop_free_action)
        crop_menu.addAction(self.crop_2_3_action)
        crop_menu.addAction(self.crop_3_4_action)
        crop_menu.addSeparator()
        crop_menu.addAction(self.apply_crop_action)
        
        # View menu
        view_menu = menubar.addMenu('&View')
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
        navigate_menu = menubar.addMenu('&Navigate')
        navigate_menu.addAction(self.prev_action)
        navigate_menu.addAction(self.next_action)
        
        # Settings menu
        settings_menu = menubar.addMenu('&Settings')
        settings_menu.addAction(self.set_api_key_action)

    def _create_toolbar(self):
        """Create the application toolbar"""
        self.toolbar = QToolBar("Main Controls")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.tool_button_icon_size = QSize(24, 24)
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
        navigate_actions = [self.prev_action, self.next_action]
        edit_actions = [self.rotate_left_action, self.rotate_right_action, 
                       self.remove_bg_action, self.crop_mode_action,
                       self.apply_crop_action, self.delete_action]
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
            tooltip_text = action.toolTip() if action.toolTip() else action.text().replace("&", "")
            button.setToolTip(tooltip_text)
            layout.addWidget(button)

    def _create_separator(self):
        """Create a vertical separator for toolbar"""
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator

    def _load_initial_image(self):
        """Load the initial image if provided"""
        if not self.initial_image_to_load:
            return
            
        if not QFile.exists(self.initial_image_to_load):
            self.status_bar.showMessage(f"File not found: {self.initial_image_to_load}", 5000)
            return
            
        info = QFileInfo(self.initial_image_to_load)
        supported_formats = [bytes(fmt).decode().lower() 
                           for fmt in QImageReader.supportedImageFormats()]
                           
        if info.suffix().lower() in supported_formats:
            self.load_image(self.initial_image_to_load)
        else:
            self.status_bar.showMessage(
                f"Unsupported file format: {self.initial_image_to_load}",
                5000
            )

    def load_image(self, file_path):
        """Load an image from file"""
        new_pixmap = QPixmap()
        if not new_pixmap.load(file_path):
            self.status_bar.showMessage(
                f"Failed to load image: {os.path.basename(file_path)}",
                5000
            )
            return False
            
        self.pixmap = new_pixmap
        self.current_image_path = file_path
        self.status_bar.showMessage(f"Opened: {os.path.basename(file_path)}")
        
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
        
        return True

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
                self.status_bar.showMessage(f"Cannot display: {filename}")
            else:
                self.status_bar.showMessage("No image to display")
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
                # This should be max, not min, to find the larger of the two required scales
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
            
            # Update status bar
            self._update_status_bar()
            
        except Exception as e:
            print(f"Error updating image display: {e}")
            self.status_bar.showMessage("Error displaying image")

    def _update_status_bar(self):
        """Update the status bar with current image information"""
        if self.pixmap.isNull():
            self.status_bar.showMessage("No image loaded")
            return
        
        img_name = os.path.basename(self.current_image_path) if self.current_image_path else "Unsaved Image"
        
        # Add modification indicators
        mods = []
        if self.image_modified_by_bg_removal:
            mods.append("no bg")
        if self.image_modified_by_crop:
            mods.append("cropped")
        
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
            f"Zoom: {self.scale_factor*100:.0f}% | "
            f"Rotation: {self.rotation_angle}°"
        )
        
        self.status_bar.showMessage(status_msg)

    def _navigate_image(self, direction):
        """Navigate to next/previous image in directory"""
        if not self.image_files_in_directory:
            self.status_bar.showMessage("No image files in directory", 2000)
            return False
            
        num_files = len(self.image_files_in_directory)
        if num_files <= 1: # No navigation if 0 or 1 image
            self.status_bar.showMessage("No other images in this directory", 2000)
            return False
            
        # Check for unsaved changes
        has_unsaved_changes = (
            self.rotation_angle != 0 or 
            self.image_modified_by_bg_removal or 
            self.image_modified_by_crop
        )
        
        if has_unsaved_changes:
            filename = os.path.basename(self.current_image_path) if self.current_image_path else "untitled image"
            reply = QMessageBox.question(
                self, 
                "Unsaved Changes", 
                f"Image '{filename}' has unsaved changes. Save before navigating?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                if not self.save_image():
                    return False # Stop navigation if save fails or is cancelled
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
                    f"Skipping unreadable file: {os.path.basename(file_to_try)}", 2000)
                next_index = (next_index + direction) % num_files

        self.status_bar.showMessage("No other readable images found", 3000)
        return False

    def open_image_dialog(self):
        """Show open file dialog"""
        settings = QSettings()
        last_dir = settings.value("last_opened_directory", QDir.homePath())
        
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
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
            f"Common Image Files ({common_formats});;"
            f"All Supported Files ({all_supported});;"
            f"All Files (*)"
        )

    def save_image(self):
        """Save current image to its original file"""
        if self.pixmap.isNull():
            self.status_bar.showMessage("No image to save", 2000)
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
            self.status_bar.showMessage(f"Image saved to {file_to_save}", 3000)
            # Reset state and reload to reflect saved state
            self.rotation_angle = 0
            self.image_modified_by_crop = False # Crop is already applied to self.pixmap
            self.load_image(file_to_save) 
            return True
        else:
            self.status_bar.showMessage(f"Failed to save to {file_to_save}", 3000)
            QMessageBox.warning(self, "Save Error", f"Could not save image to {file_to_save}")
            return False

    def save_image_as(self):
        """Save current image to a new file"""
        if self.pixmap.isNull():
            return False
            
        base_path = self.current_image_path or QSettings().value(
            "last_opened_directory", QDir.homePath())
        
        file_name, selected_filter = self._get_save_filename("Save Image As", base_path)
        if not file_name:
            return False
            
        # Apply transformations
        pixmap_to_save = self.pixmap
        if self.rotation_angle != 0:
            transform = QTransform()
            transform.rotate(self.rotation_angle)
            pixmap_to_save = pixmap_to_save.transformed(transform, Qt.SmoothTransformation)
            
        if pixmap_to_save.save(file_name):
            self.status_bar.showMessage(f"Image saved to {file_name}", 3000)
            # After saving as, the new file becomes the current one
            self.load_image(file_name) 
            return True
        else:
            self.status_bar.showMessage(f"Failed to save to {file_name}", 3000)
            QMessageBox.warning(self, "Save Error", f"Could not save image to {file_name}")
            return False

    def _get_save_filename(self, purpose, base_path):
        """Get filename for saving with appropriate defaults"""
        if base_path and os.path.isfile(base_path):
            original_dir = os.path.dirname(base_path)
            original_basename, original_ext = os.path.splitext(os.path.basename(base_path))
        else:
            original_dir = base_path if os.path.isdir(base_path) else QDir.homePath()
            original_basename = "untitled"
            original_ext = ".png" # Default to png for new files
        
        suffix_mod = ""
        if self.rotation_angle != 0:
            suffix_mod += "_rotated"
        if self.image_modified_by_crop:
            suffix_mod += "_cropped"
        if self.image_modified_by_bg_removal:
            suffix_mod += "_no_bg"
            original_ext = ".png" # Force PNG for transparency
            
        default_name = f"{original_basename}{suffix_mod}{original_ext}"
        default_path = os.path.join(original_dir, default_name)
        
        filters = "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;BMP Files (*.bmp);;All Files (*)"
        
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
        new_color = QColorDialog.getColor(self.viewer_bg_color, self, "Select Background Color")
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
            QMessageBox.information(self, "Properties", "No image loaded.")
            return

        info = QFileInfo(self.current_image_path)
        properties = [
            f"<b>File:</b> {info.fileName()}",
            f"<b>Path:</b> {info.absoluteFilePath()}",
            f"<b>Size:</b> {self.pixmap.width()} x {self.pixmap.height()} pixels",
            f"<b>File Size:</b> {info.size() / 1024:.2f} KB",
            f"<b>Created:</b> {info.birthTime().toString(Qt.DefaultLocaleLongDate)}",
            f"<b>Modified:</b> {info.lastModified().toString(Qt.DefaultLocaleLongDate)}",
            f"<b>Depth:</b> {self.pixmap.depth()}-bit",
        ]
        QMessageBox.information(self, "Image Properties", "<br>".join(properties))

    def copy_image_to_clipboard(self):
        """Copy the currently displayed image to the system clipboard."""
        if not self.pixmap.isNull():
            QApplication.clipboard().setPixmap(self.image_label.pixmap())
            self.status_bar.showMessage("Image copied to clipboard", 2000)

    def delete_current_image(self):
        """Delete the current image file (moves to trash if available)."""
        if not self.current_image_path or not os.path.exists(self.current_image_path):
            self.status_bar.showMessage("No file to delete", 2000)
            return

        file_name = os.path.basename(self.current_image_path)
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete '{file_name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            path_to_delete = self.current_image_path
            if self._navigate_image(1) or self._navigate_image(-1):
                # Navigation successful, now delete
                try:
                    if SEND2TRASH_AVAILABLE:
                        send2trash.send2trash(path_to_delete)
                        self.status_bar.showMessage(f"Moved '{file_name}' to trash", 3000)
                    else:
                        os.remove(path_to_delete)
                        self.status_bar.showMessage(f"Permanently deleted '{file_name}'", 3000)
                    self.load_directory_images(self.current_image_path) # Refresh file list
                except Exception as e:
                    QMessageBox.warning(self, "Delete Error", f"Could not delete file: {e}")
                    self.load_image(path_to_delete) # Reload if delete failed
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
                    QMessageBox.warning(self, "Delete Error", f"Could not delete file: {e}")


    def process_remove_background(self):
        """Handle the background removal process."""
        if self.pixmap.isNull() or not REQUESTS_AVAILABLE:
            return

        if not self.remove_bg_api_key:
            QMessageBox.information(self, "API Key Required", 
                                    "Please set your remove.bg API key in Settings -> Set API Key...")
            return

        self.status_bar.showMessage("Removing background, please wait...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            response = requests.post(
                'https://api.remove.bg/v1.0/removebg',
                files={'image_file': open(self.current_image_path, 'rb')},
                data={'size': 'auto'},
                headers={'X-Api-Key': self.remove_bg_api_key},
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            new_pixmap = QPixmap()
            new_pixmap.loadFromData(response.content)
            
            if not new_pixmap.isNull():
                self.pixmap = new_pixmap
                self.image_modified_by_bg_removal = True
                self.rotation_angle = 0 # Reset rotation
                self.update_image_display()
                self.status_bar.showMessage("Background removed successfully. Save the new image.", 5000)
            else:
                raise ValueError("Failed to load image from API response.")

        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self, "API Error", f"Network or API error: {e}")
            self.status_bar.showMessage("Background removal failed.", 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {e}")
            self.status_bar.showMessage("Background removal failed.", 5000)
        finally:
            QApplication.restoreOverrideCursor()
            self.update_actions_state()

    def show_set_api_key_dialog(self):
        """Show dialog to set the remove.bg API key."""
        dialog = ApiKeyDialog(self.remove_bg_api_key, self)
        if dialog.exec_() == QDialog.Accepted:
            self._save_api_key(dialog.get_api_key())
            self.status_bar.showMessage("API Key saved.", 2000)

    def toggle_crop_mode(self, checked):
        """Toggle cropping mode on or off."""
        self.is_cropping = checked
        if self.is_cropping:
            self.setCursor(Qt.CrossCursor)
            self.rubber_band = QRubberBand(QRubberBand.Rectangle, self.image_label)
        else:
            self.setCursor(Qt.ArrowCursor)
            if self.rubber_band:
                self.rubber_band.hide()
            self.rubber_band = None
            self.current_selection_rect_on_label = None
        self.update_actions_state()

    def set_crop_ratio(self, ratio):
        """Set the aspect ratio for cropping."""
        self.current_crop_ratio = ratio

    def apply_crop_from_selection(self):
        """Apply the crop based on the rubber band selection."""
        if self.pixmap.isNull() or not self.current_selection_rect_on_label:
            return

        # Map selection rectangle from label coordinates to original pixmap coordinates
        label_pixmap = self.image_label.pixmap()
        if label_pixmap.isNull(): return

        # Calculate the actual displayed pixmap's top-left corner on the label
        label_w, label_h = self.image_label.width(), self.image_label.height()
        pixmap_w, pixmap_h = label_pixmap.width(), label_pixmap.height()
        offset_x = (label_w - pixmap_w) // 2
        offset_y = (label_h - pixmap_h) // 2
        
        # Translate selection rect to be relative to the pixmap on the label
        selection_on_pixmap = self.current_selection_rect_on_label.translated(-offset_x, -offset_y)

        # Scale the selection rectangle to match the original (un-rotated, un-scaled) pixmap
        scale = self.pixmap.width() / (label_pixmap.width() / self.scale_factor)
        
        crop_rect_on_original = QRect(
            int(selection_on_pixmap.x() * scale),
            int(selection_on_pixmap.y() * scale),
            int(selection_on_pixmap.width() * scale),
            int(selection_on_pixmap.height() * scale)
        )
        
        # Perform the crop on the original pixmap
        cropped_pixmap = self.pixmap.copy(crop_rect_on_original)
        
        if not cropped_pixmap.isNull():
            self.pixmap = cropped_pixmap
            self.image_modified_by_crop = True
            self.toggle_crop_mode(False) # Exit crop mode
            self.crop_mode_action.setChecked(False)
            self.fit_to_window()
            self.update_actions_state()

    def update_actions_state(self):
        """Enable or disable actions based on the current state."""
        has_image = not self.pixmap.isNull()
        has_files_in_dir = len(self.image_files_in_directory) > 1
        
        self.save_action.setEnabled(has_image)
        self.save_as_action.setEnabled(has_image)
        self.copy_action.setEnabled(has_image)
        self.delete_action.setEnabled(has_image and self.current_image_path is not None)
        self.properties_action.setEnabled(has_image)
        
        self.remove_bg_action.setEnabled(has_image and REQUESTS_AVAILABLE and bool(self.remove_bg_api_key))
        
        self.zoom_in_action.setEnabled(has_image)
        self.zoom_out_action.setEnabled(has_image)
        self.fit_window_action.setEnabled(has_image)
        self.actual_size_action.setEnabled(has_image)
        self.rotate_left_action.setEnabled(has_image)
        self.rotate_right_action.setEnabled(has_image)
        
        self.crop_mode_action.setEnabled(has_image)
        self.apply_crop_action.setEnabled(has_image and self.is_cropping and self.current_selection_rect_on_label is not None)
        
        self.next_action.setEnabled(has_files_in_dir)
        self.prev_action.setEnabled(has_files_in_dir)

        self._update_status_bar()

    def eventFilter(self, source, event):
        """Filter events for mouse interaction on the image label for cropping."""
        if source is self.image_label and self.is_cropping:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.crop_origin_point_on_label = event.pos()
                self.rubber_band.setGeometry(QRect(self.crop_origin_point_on_label, QSize()))
                self.rubber_band.show()
                return True
            elif event.type() == QEvent.MouseMove and self.crop_origin_point_on_label:
                current_pos = event.pos()
                
                if self.current_crop_ratio:
                    w_ratio, h_ratio = self.current_crop_ratio
                    delta = current_pos - self.crop_origin_point_on_label
                    new_width = delta.x()
                    new_height = int(new_width * h_ratio / w_ratio)
                    # Adjust height based on width to maintain ratio
                    current_pos.setY(self.crop_origin_point_on_label.y() + new_height)

                self.current_selection_rect_on_label = QRect(self.crop_origin_point_on_label, current_pos).normalized()
                self.rubber_band.setGeometry(self.current_selection_rect_on_label)
                self.update_actions_state()
                return True
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self.crop_origin_point_on_label = None
                return True

        return super().eventFilter(source, event)
    
    def resizeEvent(self, event):
        """Handle window resize event to refit image if necessary."""
        super().resizeEvent(event)
        self.fit_to_window()


# --- BLOK EKSEKUSI APLIKASI ---
# Kode ini membuat dan menjalankan aplikasi.

if __name__ == '__main__':
    # 1. Membuat instance QApplication.
    app = QApplication(sys.argv)
    
    # 2. Membuat instance dari jendela utama.
    #    Memeriksa apakah ada path gambar yang diberikan dari command line.
    image_to_open = sys.argv[1] if len(sys.argv) > 1 else None
    viewer = ImageViewer(image_path=image_to_open)
    
    # 3. Menampilkan jendela.
    viewer.show()
    
    # 4. Memulai event loop aplikasi dan memastikan keluar dengan bersih.
    sys.exit(app.exec_())