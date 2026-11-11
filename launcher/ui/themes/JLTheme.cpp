// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
#include "JLTheme.h"

#include <QObject>

namespace {
// Surfaces, from back to front.
constexpr auto kBackground = "#0B0B0C";
constexpr auto kSurface = "#101012";
constexpr auto kRaised = "#17171A";
constexpr auto kBorder = "#26262B";
constexpr auto kText = "#F2F2F3";
constexpr auto kMuted = "#8B8B93";
}  // namespace

QString JLTheme::id()
{
    return "jl-dark";
}

QString JLTheme::name()
{
    return QObject::tr("JL Dark");
}

QString JLTheme::tooltip()
{
    return QObject::tr("The default JL look: near-black surfaces, one accent, no clutter.");
}

QPalette JLTheme::colorScheme()
{
    QPalette palette;
    palette.setColor(QPalette::Window, QColor(kBackground));
    palette.setColor(QPalette::WindowText, QColor(kText));
    palette.setColor(QPalette::Base, QColor(kSurface));
    palette.setColor(QPalette::AlternateBase, QColor(kRaised));
    palette.setColor(QPalette::ToolTipBase, QColor(kRaised));
    palette.setColor(QPalette::ToolTipText, QColor(kText));
    palette.setColor(QPalette::Text, QColor(kText));
    palette.setColor(QPalette::PlaceholderText, QColor(kMuted));
    palette.setColor(QPalette::Button, QColor(kRaised));
    palette.setColor(QPalette::ButtonText, QColor(kText));
    palette.setColor(QPalette::BrightText, QColor("#FF6B6B"));
    palette.setColor(QPalette::Link, QColor("#D9D9DE"));
    // A neutral selection keeps the palette monochrome; the stylesheet restyles
    // item views so selection reads as a subtle raised surface.
    palette.setColor(QPalette::Highlight, QColor("#2A2A30"));
    palette.setColor(QPalette::HighlightedText, QColor(kText));
    palette.setColor(QPalette::Light, QColor(kRaised));
    palette.setColor(QPalette::Midlight, QColor(kBorder));
    palette.setColor(QPalette::Dark, QColor(kSurface));
    palette.setColor(QPalette::Mid, QColor(kBorder));
    palette.setColor(QPalette::Shadow, QColor("#000000"));
    return fadeInactive(palette, fadeAmount(), fadeColor());
}

double JLTheme::fadeAmount()
{
    return 0.45;
}

QColor JLTheme::fadeColor()
{
    return QColor(kBackground);
}

QString JLTheme::qtTheme()
{
    return "Fusion";
}

bool JLTheme::hasStyleSheet()
{
    return true;
}

QString JLTheme::appStyleSheet()
{
    // Deliberately restrained: radius, spacing and one accent colour. Everything
    // that Fusion already draws well is left alone.
    return QStringLiteral(R"(
QToolTip {
    color: #F2F2F3;
    background-color: #17171A;
    border: 1px solid #26262B;
    border-radius: 6px;
    padding: 5px 8px;
}

QMainWindow, QDialog {
    background-color: #0B0B0C;
}

QToolBar {
    background: transparent;
    border: none;
    spacing: 2px;
    padding: 4px 8px;
}

QToolBar::separator {
    background: #26262B;
    width: 1px;
    margin: 6px 6px;
}

QToolButton {
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 8px;
}
QToolButton:hover {
    background-color: #17171A;
    border-color: #26262B;
}
QToolButton:pressed {
    background-color: #101012;
}
QToolButton:checked {
    background-color: #202026;
    border-color: #2E2E35;
}
QToolButton::menu-indicator {
    image: none;
}

QPushButton {
    background-color: #17171A;
    border: 1px solid #26262B;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 18px;
}
QPushButton:hover {
    background-color: #1D1D21;
    border-color: #34343C;
}
QPushButton:pressed {
    background-color: #121215;
}
QPushButton:default {
    background-color: #F2F2F3;
    color: #0B0B0C;
    border-color: #F2F2F3;
}
QPushButton:default:hover {
    background-color: #FFFFFF;
}
QPushButton:disabled {
    color: #6A6A72;
    background-color: #131316;
    border-color: #1F1F24;
}
QPushButton:checked {
    background-color: #202026;
    border-color: #2E2E35;
}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #101012;
    border: 1px solid #26262B;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #34343C;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #4A4A54;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    color: #6A6A72;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #131316;
    border: 1px solid #26262B;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}

QTabWidget::pane {
    border: 1px solid #1D1D22;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #8B8B93;
    border: none;
    padding: 7px 14px;
    margin-right: 2px;
}
QTabBar::tab:hover {
    color: #D9D9DE;
}
QTabBar::tab:selected {
    color: #F2F2F3;
    border-bottom: 2px solid #F2F2F3;
}

QListView, QTreeView, QTableView {
    background-color: #101012;
    border: 1px solid #1D1D22;
    border-radius: 8px;
    outline: none;
    alternate-background-color: #101012;
}
QListView::item, QTreeView::item, QTableView::item {
    border: none;
    padding: 3px 4px;
}
QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {
    background-color: #17171A;
}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {
    background-color: #26262B;
    color: #FFFFFF;
}
QHeaderView::section {
    background-color: transparent;
    color: #8B8B93;
    border: none;
    border-bottom: 1px solid #1D1D22;
    padding: 6px 8px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2E2E35;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #3D3D46;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #2E2E35;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
    width: 0;
    height: 0;
}

QSplitter::handle {
    background: transparent;
}
QGroupBox {
    border: 1px solid #1D1D22;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #8B8B93;
}

QProgressBar {
    background-color: #101012;
    border: 1px solid #1D1D22;
    border-radius: 6px;
    text-align: center;
    min-height: 14px;
}
QProgressBar::chunk {
    background-color: #F2F2F3;
    border-radius: 5px;
}

QMenu {
    background-color: #131316;
    border: 1px solid #26262B;
    border-radius: 8px;
    padding: 5px;
}
QMenu::item {
    padding: 6px 22px 6px 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background-color: #26262B;
}
QMenu::separator {
    height: 1px;
    background: #26262B;
    margin: 5px 8px;
}

/* The instance name is a QTextEdit inside EditableLabel. Without an explicit rule it
   inherits the palette's Text colour on a transparent Base, which renders as a clipped,
   doubled glyph run on the dark background. Give it its own transparent surface. */
QTextEdit#nameLabel, QWidget#nameLabel QTextEdit {
    background: transparent;
    border: none;
    color: #F2F2F3;
    selection-background-color: #2B2B31;
}

QStatusBar {
    background: transparent;
    border-top: 1px solid #1D1D22;
}
QStatusBar::item {
    border: none;
}
)");
}
