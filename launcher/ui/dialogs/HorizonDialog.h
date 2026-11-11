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
#include <QUrl>

class QLabel;
class QPlainTextEdit;
class QProgressBar;
class QPushButton;
class NetJob;
class Task;

/**
 * Installs and launches Horizon, the Rust reimplementation of Minecraft: Java Edition.
 *
 * Horizon is a separate native program, not a Minecraft instance: it cannot be started by
 * a Java launcher, and its mods are `.hnmod` / Rust-to-WebAssembly rather than Fabric jars.
 * This dialog therefore does what a launcher legitimately can: fetch the official Horizon
 * launcher for this platform from its GitHub releases, keep it in JL's data directory, and
 * run it. Mods and resource packs are then managed by Horizon itself.
 *
 * JL ships none of Horizon's code or assets; the button in About goes to the project so
 * its developers get the support.
 */
class HorizonDialog : public QDialog {
    Q_OBJECT

   public:
    explicit HorizonDialog(QWidget* parent = nullptr);

    /// \brief Where the downloaded launcher lives.
    static QString installDir();

   private slots:
    void checkForLauncher();
    void downloadLauncher();
    void runHorizon();
    void openProjectPage();

   private:
    void appendLog(const QString& line);
    void setBusy(bool busy);
    void resolveLocalLauncher();
    void fail(const QString& reason);

    QLabel* m_status = nullptr;
    QPlainTextEdit* m_log = nullptr;
    QProgressBar* m_progress = nullptr;
    QPushButton* m_check = nullptr;
    QPushButton* m_download = nullptr;
    QPushButton* m_run = nullptr;
    QPushButton* m_support = nullptr;

    QString m_launcherPath;
    QString m_downloadUrl;
    QString m_releaseTag;
};
