// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonModFolderPage.h"

// m_ui is only forward declared by ExternalResourcesPage.h; touching it needs the generated
// header (as ModFolderPage.cpp does).
#include "ui_ExternalResourcesPage.h"

#include <QAction>
#include <QIcon>
#include <QMessageBox>
#include <QProcess>

#include "Application.h"
#include "FileSystem.h"
#include "minecraft/HorizonInstance.h"
#include "ui/widgets/WideBar.h"

HorizonModFolderPage::HorizonModFolderPage(HorizonInstance* inst, ModFolderModel* model, QWidget* parent)
    : ModFolderPage(inst, model, parent), m_horizon(inst)
{
    // Horizon cannot use the Java download/update paths: those fetch Fabric jars.
    m_ui->actionDownloadItem->setVisible(false);
    m_ui->actionUpdateItem->setVisible(false);

    m_buildAction = new QAction(tr("Build Mods"), this);
    m_buildAction->setIcon(QIcon::fromTheme("launch"));
    m_buildAction->setToolTip(
        tr("Horizon compiles native mods (.hnmod) into the game before it can run.\n"
           "This runs Horizon's own native-build, so a new mod actually takes effect."));
    m_ui->actionsToolbar->insertActionBefore(m_ui->actionAddItem, m_buildAction);
    connect(m_buildAction, &QAction::triggered, this, &HorizonModFolderPage::buildMods);
}

void HorizonModFolderPage::buildMods()
{
    if (m_build) {
        QMessageBox::information(this, tr("Already building"), tr("A Horizon build is already running."));
        return;
    }

    const auto launcher = m_horizon->horizonLauncher();
    if (launcher.isEmpty()) {
        QMessageBox::warning(this, tr("Horizon launcher not found"),
                             tr("Building mods needs Horizon's launcher (horizon-launcher), which could not be "
                                "found.\n\nInstall it from Help → Horizon, or put horizon-launcher next to "
                                "the Horizon client."));
        return;
    }

    const auto modsDir = m_horizon->modsRoot();
    if (!FS::ensureFolderPathExists(modsDir)) {
        QMessageBox::warning(this, tr("Could not create the mods folder"), modsDir);
        return;
    }

    m_buildAction->setEnabled(false);
    m_build = new QProcess(this);
    m_build->setProgram(launcher);
    // Horizon's documented form: native-build <mods dir> --trust-native-code
    m_build->setArguments({ "native-build", modsDir, "--trust-native-code" });
    m_build->setWorkingDirectory(m_horizon->gameRoot());
    m_build->setProcessChannelMode(QProcess::MergedChannels);

    connect(m_build, &QProcess::readyRead, this, [this] {
        if (m_build) {
            appendBuildOutput(QString::fromLocal8Bit(m_build->readAll()));
        }
    });
    connect(m_build, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            finishBuild(-1, true);
        }
    });
    connect(m_build, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this](int exitCode, QProcess::ExitStatus) { finishBuild(exitCode, false); });

    appendBuildOutput(tr("Running %1 native-build\n").arg(launcher));
    m_build->start();
}

void HorizonModFolderPage::appendBuildOutput(const QString& text)
{
    // Horizon's build is long (it compiles Rust). Surface it in the launcher log so it can be
    // followed from the console tab instead of a frozen-looking page.
    for (const auto& line : text.split('\n')) {
        if (!line.trimmed().isEmpty()) {
            qDebug().noquote() << "[Horizon build]" << line;
        }
    }
}

void HorizonModFolderPage::finishBuild(int exitCode, bool failedToStart)
{
    if (m_build) {
        appendBuildOutput(QString::fromLocal8Bit(m_build->readAll()));
        m_build->deleteLater();
        m_build = nullptr;
    }
    if (m_buildAction) {
        m_buildAction->setEnabled(true);
    }

    if (failedToStart) {
        QMessageBox::critical(this, tr("Build failed"),
                              tr("Horizon's launcher could not be started. Check that it still exists and is "
                                 "executable."));
        return;
    }

    if (exitCode == 0) {
        QMessageBox::information(this, tr("Mods built"),
                                 tr("Horizon rebuilt the game with the mods in this instance.\n\n"
                                    "Press Play to run it."));
    } else {
        QMessageBox::warning(this, tr("Build failed"),
                             tr("Horizon's launcher exited with code %1.\n\n"
                                "The build output is in the launcher log.")
                                 .arg(exitCode));
    }
}
