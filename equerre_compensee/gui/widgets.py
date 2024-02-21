#! python3  # noqa: E265

# standard
import math
import os
from typing import Union

import equerre_compensee
from equerre_compensee.utils import tolerance_threshold, xpm_cursor

# PyQGIS
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsSimpleMarkerSymbolLayerBase,
    QgsVectorLayer,
    QgsWkbTypes,
    edit,
)
from qgis.gui import (
    QgisInterface,
    QgsDockWidget,
    QgsDoubleSpinBox,
    QgsMapCanvas,
    QgsMapTool,
    QgsRubberBand,
    QgsSnapIndicator,
)
from qgis.PyQt.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor, QFocusEvent, QIcon, QKeySequence, QPixmap
from qgis.PyQt.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

PLUGIN_PATH = os.path.dirname(equerre_compensee.__file__)
ICON_MAPTOOL = QIcon(
    os.path.join(PLUGIN_PATH, "resources", "images", "square_tool.svg")
)
ICON_CAPTURE = QIcon(
    os.path.join(PLUGIN_PATH, "resources", "images", "mActionCapturePoint.svg")
)
EPSG = "EPSG:3948"


class InfoLabel(QLabel):
    """Frameless label usefull for tool tips"""

    def __init__(self, parent: QWidget = None):
        """
        param parent: parent widget
        """
        super().__init__(
            parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAlignment(Qt.AlignRight)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)


class QgsDoubleSpinBoxV2(QgsDoubleSpinBox):
    """QgsDoubleSpinBox that selects the content on focus in"""

    def focusInEvent(self, event: QFocusEvent) -> None:
        """
        param event: focus event
        """
        QgsDoubleSpinBox.focusInEvent(self, event)
        QTimer.singleShot(0, self.selectAll)


class CompasatedSquareDock(QgsDockWidget):
    """A DockWidget to create compensated square points"""

    def __init__(self, iface: QgisInterface, parent: QWidget = None):
        """
        param iface: a QGIS interface
        param parent: parent widget
        """
        super().__init__(parent)

        self.iface = iface
        self.setWindowTitle("Équerre compensée")
        self._canvas = self.iface.mapCanvas()
        self._point_lyr_name = "Points compensés"
        central_widget = QWidget()
        self.setWidget(central_widget)
        self._main_lyt = QHBoxLayout(central_widget)
        self._form_lyt = QFormLayout()
        self._tools_lyt = QVBoxLayout()
        self._main_lyt.addLayout(self._form_lyt)
        self._main_lyt.addLayout(self._tools_lyt)
        spinbox_configs = {
            "distance_one": {
                "label": "Distance <u>1</u> :",
                "min": -9999,
                "max": 9999,
                "clearvalue": 0,
                "decimals": 4,
                "tooltip": "Distance en abscisse (Ctrl+1)",
            },
            "distance_two": {
                "label": "Distance <u>2</u> :",
                "min": -9999,
                "max": 9999,
                "clearvalue": 0,
                "decimals": 4,
                "tooltip": "Distance en ordonnée (Ctrl+2)",
            },
            "distance_measured": {
                "label": "Mesurée :",
                "min": 0,
                "max": 9999,
                "clearvalue": 0,
                "decimals": 4,
                "tooltip": "Distance mesurée sur le plan (Ctrl+3)",
            },
        }
        for spinbox, config in spinbox_configs.items():
            setattr(self, f"_{spinbox}", QgsDoubleSpinBoxV2())
            spin_widget = getattr(self, f"_{spinbox}")
            spin_widget.setObjectName(spinbox)
            spin_widget.setMinimum(config["min"])
            spin_widget.setMaximum(config["max"])
            spin_widget.setClearValue(config["clearvalue"])
            spin_widget.setDecimals(config["decimals"])
            spin_widget.setToolTip(config["tooltip"])
            spin_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            spin_widget.valueChanged.connect(self.set_point)
            spin_widget.installEventFilter(self)
            self._form_lyt.addRow(config["label"], spin_widget)
            spin_label = self._form_lyt.labelForField(spin_widget)
            spin_label.setToolTip(config["tooltip"])

        self.le_tolerance = QLineEdit()
        self.le_tolerance.setReadOnly(True)
        self.le_tolerance.setToolTip("Seuil d'erreur toléré")
        self.pb_square_tool = QPushButton(ICON_MAPTOOL, "", central_widget)
        self.pb_square_tool.setMinimumSize(30, 30)
        self.pb_square_tool.setMaximumSize(30, 30)
        self.pb_square_tool.setIconSize(QSize(30, 30))
        self.pb_square_tool.setToolTip("Outil équerre compensée")
        self.pb_create_point = QPushButton(ICON_CAPTURE, "", central_widget)
        self.pb_create_point.setMinimumSize(30, 30)
        self.pb_create_point.setMaximumSize(30, 30)
        self.pb_create_point.setIconSize(QSize(28, 28))
        self.pb_create_point.setToolTip("Créer un point")
        spacerItem = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        # assembly
        self._form_lyt.addRow("Tolérance", self.le_tolerance)
        self._tools_lyt.addWidget(self.pb_square_tool)
        self._tools_lyt.addWidget(self.pb_create_point)
        self._tools_lyt.addItem(spacerItem)
        self._square_tool = CompensatedSquareTool(self._canvas, self)
        # shortcuts
        self._cancel_shortcut = QShortcut(
            QKeySequence(Qt.Key_Escape), self.iface.mainWindow()
        )
        self._cancel_shortcut.setContext(Qt.ApplicationShortcut)
        self._distance_one_shortcut = QShortcut(QKeySequence("Ctrl+1"), self)
        self._distance_two_shortcut = QShortcut(QKeySequence("Ctrl+2"), self)
        self._measured_distance_shortcut = QShortcut(QKeySequence("Ctrl+3"), self)
        # signals
        self._cancel_shortcut.activated.connect(self._square_tool.deactivate)
        self._distance_one_shortcut.activated.connect(
            lambda: self._distance_one.setFocus(Qt.TabFocusReason)
        )
        self._distance_two_shortcut.activated.connect(
            lambda: self._distance_two.setFocus(Qt.TabFocusReason)
        )
        self._measured_distance_shortcut.activated.connect(
            lambda: self._distance_measured.setFocus(Qt.TabFocusReason)
        )
        self.pb_square_tool.clicked.connect(self.set_map_tool)
        self.pb_create_point.clicked.connect(self.create_point)
        self._square_tool.pointCreated.connect(self.create_point)
        QgsProject.instance().crsChanged.connect(self.crs_changed)
        # initial state
        self.crs_changed()
        self.set_tolerance()

    @property
    def distance_one(self) -> float:
        return self._distance_one.value()

    @distance_one.setter
    def distance_one(self, new_distance: float) -> None:
        if isinstance(new_distance, float) or isinstance(new_distance, int):
            self._distance_one.setValue(new_distance)

    @property
    def distance_two(self) -> float:
        return self._distance_two.value()

    @distance_two.setter
    def distance_two(self, new_distance: float) -> None:
        if isinstance(new_distance, float) or isinstance(new_distance, int):
            self._distance_two.setValue(new_distance)

    @property
    def distance_measured(self) -> float:
        return self._distance_measured.value()

    @distance_measured.setter
    def distance_measured(self, new_distance: float) -> None:
        if isinstance(new_distance, float) or isinstance(new_distance, int):
            self._distance_measured.setValue(new_distance)

    @property
    def ratio_one(self) -> float:
        """Get the ratio between the first distance and the measured one"""
        return (
            self.distance_one / self.distance_measured
            if self.distance_measured != 0
            else 0
        )

    def crs_changed(self) -> None:
        """On CRS change"""
        self.setEnabled(QgsProject.instance().crs().authid() == EPSG)
        self.iface.actionPan().trigger()

    def set_map_tool(self) -> None:
        """Activate the compensated square map tool"""
        self._canvas.setMapTool(self._square_tool)

    def create_point(self, point: Union[QgsPointXY, None] = None) -> bool:
        """Create a point in a memory layer
        param point: a point to create
        """
        if not self._square_tool.point:
            return

        layers = QgsProject.instance().mapLayersByName(self._point_lyr_name)
        tests_lyr_exists = True
        if not layers:
            tests_lyr_exists = False
        elif layers[0].dataProvider().name() != "memory":
            tests_lyr_exists = False

        if tests_lyr_exists:
            point_lyr = layers[0]
        else:
            point_lyr = QgsVectorLayer(
                f"Point?crs={EPSG}", self._point_lyr_name, "memory"
            )
            QgsProject.instance().addMapLayer(point_lyr)

        # point layer style
        point_lyr.renderer().symbol().symbolLayer(0).setShape(
            QgsSimpleMarkerSymbolLayerBase.Cross2
        )
        point_lyr.renderer().symbol().setSize(2)
        point_lyr.renderer().symbol().symbolLayer(0).setStrokeColor(QColor("#a20000"))
        point_lyr.triggerRepaint()
        iface.layerTreeView().refreshLayerSymbology(point_lyr.id())

        point_feat = QgsFeature()
        point_feat.setGeometry(QgsGeometry.fromPointXY(self._square_tool.point))
        with edit(point_lyr):
            point_lyr.addFeature(point_feat)

        return True

    def set_point(self, value: float) -> None:
        """Sets the map tool point location
        param value: a spinbox value, returned by the signal, not used
        """
        self._square_tool.update_point()
        if self.sender().objectName() == "distance_measured":
            self.set_tolerance()

    def set_tolerance(self) -> None:
        """Sets the tolerance threshold value"""
        self.le_tolerance.setText(f"{tolerance_threshold(self.distance_measured):.3f}")

    def eventFilter(self, source: QObject, event: QEvent) -> bool:
        """Catch all events on widgets with installed event filter
        param source: the Qt Object who fires the event
        param event: the fired event
        """
        if event.type() == QEvent.KeyRelease:
            if source in [
                self._distance_one,
                self._distance_two,
                self._distance_measured,
            ]:
                if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
                    self.create_point()
                    return True

        return False

    def closeEvent(self, event) -> None:
        """Close event"""
        # for shortcut working the next time in the same QGIS instance
        self._cancel_shortcut.setContext(Qt.WidgetShortcut)
        QgsDockWidget.closeEvent(self, event)


class CompensatedSquareTool(QgsMapTool):
    """
    A map tool to create a point with a compensated abscissa and an ordinate
    by comparing a measured distance with the real one
    """

    point_created = pyqtSignal(QgsPointXY, name="pointCreated")

    def __init__(self, canvas: QgsMapCanvas, dock: CompasatedSquareDock):
        """
        param canvas: a mapCanvas
        param dock: the widget with measured distances
        """
        self._canvas = canvas
        super().__init__(self._canvas)
        self._dock = dock
        self._info_label = InfoLabel()
        self._info_model = (
            "Calculée : {0:.3f}<br/>Différence : {1:.3f}<br/>Tolérance : {2}"
        )
        self.points_to_draw = []
        self.crs = QgsCoordinateReferenceSystem(EPSG)
        self.rubber_line = QgsRubberBand(self._canvas, QgsWkbTypes.LineGeometry)
        self.rubber_line.setWidth(1)
        self.rubber_line.setColor(QColor("#FF0000"))

        self.rubber_new_point = QgsRubberBand(self._canvas, QgsWkbTypes.PointGeometry)
        self.rubber_new_point.setColor(QColor("#FF0000"))

        self.snap_indicator = QgsSnapIndicator(self._canvas)
        self.snapper = self._canvas.snappingUtils()

        self.cursor = QCursor(QPixmap(xpm_cursor()))
        self.setCursor(self.cursor)

    @property
    def point(self) -> Union[QgsPointXY, None]:
        return self.rubber_new_point.getPoint(0)

    @point.setter
    def point(self, new_point: QgsGeometry) -> None:
        if isinstance(new_point, QgsGeometry):
            self.rubber_new_point.setToGeometry(new_point, self.crs)
        elif new_point is None:
            self.rubber_new_point.reset()

    def update_point(self) -> None:
        """Updates the point location"""
        if not self.line:
            return

        if self._dock.distance_measured == 0:
            point_distance_one = self._dock.distance_one
        else:
            point_distance_one = self.line.length() * self._dock.ratio_one

        # second point isn't compensated
        point_distance_two = self._dock.distance_two
        line_angle = self.line.angleAtVertex(1)

        point_x1 = self.line.vertexAt(0).x() + point_distance_one * math.sin(line_angle)
        point_y1 = self.line.vertexAt(0).y() + point_distance_one * math.cos(line_angle)
        point_x2 = point_x1 - point_distance_two * math.sin(
            line_angle + math.radians(90)
        )
        point_y2 = point_y1 - point_distance_two * math.cos(
            line_angle + math.radians(90)
        )
        point_geometry = QgsGeometry.fromPointXY(QgsPointXY(point_x2, point_y2))
        self.point = point_geometry

    @property
    def line(self) -> Union[QgsGeometry, None]:
        return self.rubber_line.asGeometry()

    @line.setter
    def line(self, new_line: Union[QgsGeometry, None]) -> None:
        if isinstance(new_line, QgsGeometry):
            self.rubber_line.setToGeometry(new_line, self.crs)
        elif new_line is None:
            self.rubber_line.reset()

    def deactivate(self):
        """Deactivates the map tool"""
        self.line = None
        self.point = None
        self.points_to_draw = []
        self._info_label.close()

    def canvasMoveEvent(self, event):
        """
        On mouse move event, updates the line and point locations
        and tool tip informations
        """
        snapMatch = self.snapper.snapToMap(event.pos())
        self.snap_indicator.setMatch(snapMatch)

        if not self.points_to_draw:
            return

        ev_mappoint = (
            self.snap_indicator.match().point()
            if self.snap_indicator.match().type()
            else event.mapPoint()
        )
        self.points_to_draw[1] = ev_mappoint

        self.line = None
        self.point = None

        self.line = QgsGeometry.fromPolylineXY(self.points_to_draw)
        self.update_point()

        if self._canvas.underMouse():
            self._info_label.move(
                self._canvas.mapToGlobal(self._canvas.mouseLastXY()).x() - 100,
                self._canvas.mapToGlobal(self._canvas.mouseLastXY()).y() + 15,
            )
            error_distance = abs(self._dock.distance_measured - self.line.length())
            is_error = error_distance > tolerance_threshold(
                self._dock.distance_measured
            )
            self.cursor = QCursor(
                QPixmap(xpm_cursor(buffer_color=["#000000", "#FFFFFF"][is_error]))
            )
            self.setCursor(self.cursor)
            info_text = self._info_model.format(
                self.line.length(), error_distance, ["✅", "❌"][is_error]
            )
            self._info_label.setText(info_text)
            self._info_label.show()

    def canvasReleaseEvent(self, event):
        """
        On mouse click event, gets the line vertices
        and emits the created point signal
        """
        snapMatch = self.snapper.snapToMap(event.pos())
        self.snap_indicator.setMatch(snapMatch)
        ev_mappoint = (
            self.snap_indicator.match().point()
            if self.snap_indicator.match().type()
            else event.mapPoint()
        )
        if self.points_to_draw:
            self.points_to_draw = []
            self._info_label.close()
            self.point_created.emit(self.point)
        else:
            self.points_to_draw = [ev_mappoint, ev_mappoint]
