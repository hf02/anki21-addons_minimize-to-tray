# -*- coding: utf-8 -*-
# Copyright: Simone Gaiarin <simgunz@gmail.com>
# License: GNU GPL, version 3 or later; http://www.gnu.org/copyleft/gpl.html
# Name: Minimize to Tray 2
# Version: 0.2
# Description: Minimize anki to tray when the X button is pressed (Anki 2 version)
# Homepage: https://github.com/simgunz/anki-plugins
# Report any problem in the github issues section
import sys
from types import MethodType

from aqt.qt import sip, Qt, QIcon, QPixmap, QApplication, QMenu, QSystemTrayIcon, QPainter, QColor, QRect, QFont, QRectF, QPainterPath 

from aqt import colors, gui_hooks, mw  # mw is the INSTANCE of the main window
from aqt.main import AnkiQt
from aqt.theme import theme_manager


class AnkiSystemTray:
    def __init__(self, mw):
        """Create a system tray with the Anki icon."""

        self.mw = mw

        config = self.mw.addonManager.getConfig(__name__)

        if "show_due" in config and config["show_due"] == False:
            self.showDueAmount = False

        if "due_font_size" in config:
            self.dueFontSize = config["due_font_size"]

        self.isAnkiFocused = True
        self.isMinimizedToTray = False
        self.lastFocusedWidget = mw
        self.explicitlyHiddenWindows = []
        self.trayIcon = self._createSystemTrayIcon()
        QApplication.setQuitOnLastWindowClosed(False)
        self._configureMw()
        self.trayIcon.show()
        self._addHooks()

        if config["hide_on_startup"]:
            self.hideAll()


    dueFontSize = 16
    showDueAmount = True

    def onActivated(self, reason):
        """Show/hide all Anki windows when the tray icon is clicked.

        The windows are shown if:
        - anki window is not in focus
        - any window is minimized
        - anki is minimize to tray
        The windows are hidden otherwise.

        The focus cannot be detected given that the main window focus is lost before this
        slot is activated. For this reason and to prevent that anki is minimized when not
        focused, on Windows are the windows are never hidden.
        """
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if (
                not self.isAnkiFocused
                or self._anyWindowMinimized()
                or self.isMinimizedToTray
            ):
                self.showAll()
            elif not sys.platform.startswith("win32"):
                self.hideAll()

    def onFocusChanged(self, old, now):
        """Keep track of the focused window in order to refocus it on showAll."""
        self.isAnkiFocused = now is not None
        if self.isAnkiFocused:
            self.lastFocusedWidget = now

    def onExit(self):
        self.mw.closeEventFromAction = True
        self.mw.close()

    def showAll(self):
        """Show all windows."""
        if self.isMinimizedToTray:
            self._showWindows(self.explicitlyHiddenWindows)
        else:
            self._showWindows(self._visibleWindows())
        if not sip.isdeleted(self.lastFocusedWidget):
            self.lastFocusedWidget.raise_()
            self.lastFocusedWidget.activateWindow()
        self.isMinimizedToTray = False

    def hideAll(self):
        """Hide all windows."""
        self.explicitlyHiddenWindows = self._visibleWindows()
        for w in self.explicitlyHiddenWindows:
            w.hide()
        self.isMinimizedToTray = True

    _displayedNumberOfCardsDue = 0
    def updateSystemTrayIcon(self, force = False):
        numberOfCardsDue = self._getAmountOfCardsDue()

        didDueCardCountChange = numberOfCardsDue != self._displayedNumberOfCardsDue
        shouldShowDueAmount = self.showDueAmount
        shouldUpdate = shouldShowDueAmount and didDueCardCountChange

        if shouldUpdate or force:
            self._displayedNumberOfCardsDue = numberOfCardsDue
            self._setSystemTrayIcon(self.trayIcon, numberOfCardsDue)

    def _addHooks(self):
        updateFunction = lambda *args : self.updateSystemTrayIcon()
        forceUpdateFunction = lambda *args : self.updateSystemTrayIcon(True)

        gui_hooks.theme_did_change.append(forceUpdateFunction)
        gui_hooks.state_did_change.append(updateFunction)
        gui_hooks.operation_did_execute.append(updateFunction)

    def _showWindows(self, windows):
        for w in windows:
            if sip.isdeleted(w):
                continue
            if w.isMinimized() == Qt.WindowState.WindowMinimized:
                # Windows that were maximized are not restored maximied unfortunately
                w.showNormal()
            else:
                # hide(): hack that solves two problems:
                # 1. focus the windows after TWO other non-Anki windows
                # gained focus (Qt bug?). Causes a minor flicker when the
                # Anki windows are already visible.
                # 2. allows avoiding to call activateWindow() on each
                # windows in order to raise them above non-Anki windows
                # and thus avoid breaking the restore-last-focus mechanism
                w.hide()
                w.show()
            w.raise_()

    def _visibleWindows(self):
        """Return the windows actually visible Anki windows.

        Anki has some hidden windows and menus that we should ignore.
        """
        windows = []
        for w in QApplication.topLevelWidgets():
            if w.isWindow() and not w.isHidden():
                if not w.children():
                    continue
                windows.append(w)
        return windows

    def _anyWindowMinimized(self):
        return any(
            w.windowState() == Qt.WindowState.WindowMinimized
            for w in self._visibleWindows()
        )
        
    def _createReviewsIcon(self, string, renderNumber = True):
        pixmap = QPixmap("icons:anki.png")

        textColor = theme_manager.qcolor(colors.STATE_LEARN)
        backgroundColor = theme_manager.qcolor(colors.CANVAS_ELEVATED)

        fontSize = self.dueFontSize
        sizeRectF = QRectF(0, 32 - fontSize, 32, fontSize)
        sizeRect = QRect(0, 32 - fontSize, 32, fontSize)

        if renderNumber:
            painter = QPainter(pixmap)

            # Draw number container

            roundedRectanglePath = QPainterPath()
            roundedRectanglePath.addRoundedRect(sizeRectF, 5, 5)

            painter.fillPath(roundedRectanglePath, backgroundColor)

            # Draw number

            font = painter.font()
            font.setPixelSize(fontSize)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)

            painter.setPen(textColor)
            painter.drawText(sizeRect, Qt.AlignmentFlag.AlignCenter, string)

            painter.end()
        
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
        return icon

    def _getAmountOfCardsDue(self):

        if not self.showDueAmount:
            # there's no need to
            # calculate this then
            return 0

        tree = self.mw.col.sched.deck_due_tree()
        children = tree.children

        total = 0

        for child in children:
            total += child.new_count
            total += child.learn_count
            total += child.review_count
        
        return total
    
    def _formatNumber(self, number):
        numberString = str(number)

        if number < 1000:
            return str(number)
        if number >= 1000 and number < 10000:
            return f"{numberString[0]}.{numberString[1]}k"
        else:
            return "∞"
    
    def _getCardsDueDisplayNumber(self, amount):
        return self._formatNumber(amount)
        
    def _setSystemTrayIcon(self, trayIcon, numberOfReviews):
        displayNumber = self._getCardsDueDisplayNumber(numberOfReviews)
        shouldShowNumber = numberOfReviews > 0 and self.showDueAmount

        ankiLogo = self._createReviewsIcon(displayNumber, shouldShowNumber)
        trayIcon.setIcon(ankiLogo)

    def _createSystemTrayIcon(self):
        trayIcon = QSystemTrayIcon(self.mw)

        numberOfReviews = self._getAmountOfCardsDue()
        self._setSystemTrayIcon(trayIcon, numberOfReviews)

        trayMenu = QMenu(self.mw)
        trayIcon.setContextMenu(trayMenu)
        showAction = trayMenu.addAction("Show all windows")
        showAction.triggered.connect(self.showAll)
        trayMenu.addAction(self.mw.form.actionExit)
        trayIcon.activated.connect(self.onActivated)
        return trayIcon

    def _configureMw(self):
        self.mw.closeEventFromAction = False
        self.mw.app.focusChanged.connect(self.onFocusChanged)
        # Disconnecting from close may have some side effects
        # (e.g. QApplication::lastWindowClosed() signal not emitted)
        self.mw.form.actionExit.triggered.disconnect(self.mw.close)
        self.mw.form.actionExit.triggered.connect(self.onExit)
        self.mw.closeEvent = self._wrapCloseCloseEvent()

    def _wrapCloseCloseEvent(self):
        """Override the close method of the mw instance."""

        def repl(self, event):
            if self.closeEventFromAction:
                # The 'Exit' action in the sys tray context menu was activated
                AnkiQt.closeEvent(self, event)
            else:
                # The main window X button was pressed
                # self.col.save()
                self.systemTray.hideAll()
                event.ignore()

        return MethodType(repl, self.mw)


def minimizeToTrayInit():
    if hasattr(mw, "trayIcon"):
        return
    mw.systemTray = AnkiSystemTray(mw)


gui_hooks.main_window_did_init.append(minimizeToTrayInit)
