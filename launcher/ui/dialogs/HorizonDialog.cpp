// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonDialog.h"

#include <QDialogButtonBox>
#include <QLabel>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QPushButton>
#include <QUrl>
#include <QVBoxLayout>

#include "Application.h"
#include "DesktopServices.h"
#include "FileSystem.h"
#include "minecraft/HorizonBuilds.h"
#include "minecraft/HorizonResources.h"

namespace {
constexpr auto kProjectUrl = "https://github.com/horizon-rust/horizon";
}

QString HorizonDialog::installDir()
{
    return HorizonBuilds::buildsRoot();
}

bool HorizonDialog::hasUsableBuild()
{
    return HorizonBuilds::isComplete(HorizonBuilds::buildDir(HorizonBuilds::newestInstalledTag()));
}

HorizonDialog::HorizonDialog(QWidget* parent) : QDialog(parent)
{
    setWindowTitle(tr("Horizon"));
    setMinimumWidth(640);

    auto* layout = new QVBoxLayout(this);

    auto* intro = new QLabel(this);
    intro->setWordWrap(true);
    intro->setText(tr("<b>Horizon</b> is a Rust reimplementation of Minecraft: Java Edition 26.3. "
                      "It ships none of Minecraft's files: JL downloads Horizon's own game files, "
                      "then Horizon prepares what it needs from your copy of Minecraft.<br><br>"
                      "Downloading the build and preparing it are the only steps. Afterwards every "
                      "Horizon instance runs it, and updating is automatic on launch."));
    layout->addWidget(intro);

    m_status = new QLabel(this);
    m_status->setWordWrap(true);
    layout->addWidget(m_status);

    m_progress = new QProgressBar(this);
    m_progress->setVisible(false);
    layout->addWidget(m_progress);

    m_log = new QPlainTextEdit(this);
    m_log->setReadOnly(true);
    m_log->setMinimumHeight(160);
    layout->addWidget(m_log);

    auto* buttons = new QDialogButtonBox(this);
    m_download = buttons->addButton(tr("Download Horizon"), QDialogButtonBox::ActionRole);
    m_prepare = buttons->addButton(tr("Prepare game files"), QDialogButtonBox::ActionRole);
    m_support = buttons->addButton(tr("Support Horizon"), QDialogButtonBox::ActionRole);
    m_close = buttons->addButton(QDialogButtonBox::Close);
    layout->addWidget(buttons);

    connect(m_download, &QPushButton::clicked, this, &HorizonDialog::downloadBuild);
    connect(m_prepare, &QPushButton::clicked, this, &HorizonDialog::prepareResources);
    connect(m_support, &QPushButton::clicked, this, &HorizonDialog::openProjectPage);
    connect(m_close, &QPushButton::clicked, this, &QDialog::accept);

    refreshStatus();
}

void HorizonDialog::refreshStatus()
{
    const auto tag = HorizonBuilds::newestInstalledTag();
    m_buildDir = HorizonBuilds::buildDir(tag);

    const bool build = HorizonBuilds::isComplete(m_buildDir);
    const auto prepared = HorizonResources::newestPrepared();

    if (!build) {
        m_status->setText(tr("<b>No Horizon build installed.</b> Press “Download Horizon” to fetch "
                             "the newest nightly build (about 30 MB)."));
    } else if (prepared.isEmpty()) {
        m_status->setText(tr("<b>Horizon %1 is installed.</b> Next, press “Prepare game files”. "
                             "Horizon will read your own Minecraft installation and build the "
                             "resources it needs — this is the step that makes it runnable.")
                              .arg(tag));
    } else {
        m_status->setText(tr("<b>Horizon %1 is ready.</b><br>Build: %2<br>Resources: %3")
                              .arg(tag, m_buildDir, prepared));
    }

    m_prepare->setEnabled(build);
    m_download->setEnabled(true);
}

void HorizonDialog::downloadBuild()
{
    setBusy(true);
    appendLog(tr("Fetching the newest Horizon build…"));

    auto* task = new HorizonDownloadTask(QString(), this);
    connect(task, &HorizonDownloadTask::logLine, this, &HorizonDialog::appendLog);
    connect(task, &Task::succeeded, this, [this, task] {
        appendLog(tr("Installed Horizon %1.").arg(task->installedTag()));
        task->deleteLater();
        setBusy(false);
        refreshStatus();
        // Straight on to the step that makes it runnable: downloading alone leaves an instance
        // that refuses to launch, which is exactly what confused people before.
        prepareResources();
    });
    connect(task, &Task::failed, this, [this, task](const QString& reason) {
        task->deleteLater();
        setBusy(false);
        fail(reason);
    });
    runTask(task);
}

void HorizonDialog::prepareResources()
{
    const auto tag = HorizonBuilds::newestInstalledTag();
    if (tag.isEmpty()) {
        fail(tr("Download a Horizon build first."));
        return;
    }

    // One prepared set per build and Minecraft version, shared by every instance of it.
    const auto output = HorizonResources::preparedDir(tag, QStringLiteral("26.3"));

    setBusy(true);
    appendLog(tr("Preparing game resources from your Minecraft into %1…").arg(output));

    auto* task = new HorizonPrepareTask(HorizonBuilds::buildDir(tag), output, this);
    connect(task, &HorizonPrepareTask::logLine, this, &HorizonDialog::appendLog);
    connect(task, &Task::succeeded, this, [this, task, output] {
        task->deleteLater();
        setBusy(false);
        appendLog(tr("Prepared %1").arg(output));
        refreshStatus();
    });
    connect(task, &Task::failed, this, [this, task](const QString& reason) {
        task->deleteLater();
        setBusy(false);
        fail(reason);
    });
    runTask(task);
}

void HorizonDialog::runTask(Task* task)
{
    m_progress->setVisible(true);
    m_progress->setRange(0, 0);
    connect(task, &Task::progress, this, [this](qint64 current, qint64 total) {
        if (total > 0 && m_progress->maximum() != static_cast<int>(total)) {
            m_progress->setRange(0, static_cast<int>(total));
        }
        m_progress->setValue(static_cast<int>(current));
    });
    connect(task, &Task::finished, this, [this] {
        m_progress->setVisible(false);
        m_progress->setRange(0, 0);
    });
    task->start();
}

void HorizonDialog::appendLog(const QString& line)
{
    m_log->appendPlainText(line);
}

void HorizonDialog::setBusy(bool busy)
{
    m_download->setEnabled(!busy);
    m_prepare->setEnabled(!busy && HorizonBuilds::isComplete(m_buildDir));
}

void HorizonDialog::fail(const QString& reason)
{
    appendLog(tr("Error: %1").arg(reason));
    m_status->setText(tr("<b>Something went wrong.</b> %1").arg(reason));
    m_progress->setVisible(false);
    refreshStatus();
}

void HorizonDialog::openProjectPage()
{
    DesktopServices::openUrl(QUrl(kProjectUrl));
}
