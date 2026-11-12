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

class QLabel;
class QPlainTextEdit;
class QProgressBar;
class QPushButton;
class Task;

/**
 * Installs Horizon: the game files, and the resources they need.
 *
 * This follows Horizon's own "Running Horizon from another launcher"
 * (docs/api/launch-guide.md):
 *
 *  1. a build is one archive per platform from a GitHub release of horizon-rust/horizon —
 *     horizon-windows-x64.zip holds horizon-client, horizon-prepare, research-lock.json and
 *     exporters/. It is the GAME FILES A LAUNCHER INSTALLS, not a launcher and not an installer;
 *  2. the newest build is the release tagged `nightly`;
 *  3. `horizon-prepare` turns the player's own Minecraft files into the resources the client
 *     reads, checked against research-lock.json. Horizon never downloads Mojang's files.
 *
 * So this dialog downloads a build, unpacks it into <dataRoot>/horizon/<tag>, then prepares
 * resources from the user's Minecraft. It never runs an installer.
 */
class HorizonDialog : public QDialog {
    Q_OBJECT

   public:
    explicit HorizonDialog(QWidget* parent = nullptr);

    /// \brief Where builds are unpacked: <dataRoot>/horizon.
    static QString installDir();

    /// \brief True when a build is unpacked and ready to run.
    static bool hasUsableBuild();

   private slots:
    void downloadBuild();
    void prepareResources();
    void openProjectPage();

   private:
    void refreshStatus();
    void appendLog(const QString& line);
    void setBusy(bool busy);
    void runTask(Task* task);
    void fail(const QString& reason);

    QLabel* m_status = nullptr;
    QPlainTextEdit* m_log = nullptr;
    QProgressBar* m_progress = nullptr;
    QPushButton* m_download = nullptr;
    QPushButton* m_prepare = nullptr;
    QPushButton* m_support = nullptr;
    QPushButton* m_close = nullptr;

    QString m_buildDir;
};
