// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#pragma once

#include <QDialog>

class QPlainTextEdit;
class QPushButton;

/**
 * Hidden diagnostic panel, opened with Alt+Shift while clicking Help.
 *
 * It exists so a maintainer can see a machine they have no access to: it collects the
 * environment, GPU, Java, account and instance facts that decide whether a feature works,
 * plus a short benchmark that measures the operations people complain about being slow.
 *
 * Nothing here uploads anything. The report is text the user copies or saves themselves.
 */
class DebugModeDialog : public QDialog {
    Q_OBJECT

   public:
    explicit DebugModeDialog(QWidget* parent = nullptr);

   private slots:
    void refresh();
    void copyReport();
    void saveReport();
    void runBenchmark();

   private:
    QPlainTextEdit* m_text = nullptr;
    QPushButton* m_refresh = nullptr;
    QPushButton* m_copy = nullptr;
    QPushButton* m_save = nullptr;
    QPushButton* m_benchmark = nullptr;

    QString m_report;
};
