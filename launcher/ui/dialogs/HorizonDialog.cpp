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

#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPlainTextEdit>
#include <QProcess>
#include <QProgressBar>
#include <QPushButton>
#include <QSysInfo>
#include <QVBoxLayout>

#include "Application.h"
#include "FileSystem.h"
#include "net/NetJob.h"
#include "net/Request.h"
#include "settings/SettingsObject.h"

namespace {

constexpr auto kProjectUrl = "https://github.com/horizon-rust/horizon";
constexpr auto kReleasesApi = "https://api.github.com/repos/horizon-rust/horizon/releases";

/// \brief The asset name suffix for this machine, or empty if Horizon has no build for it.
QString platformAssetSuffix()
{
    const auto arch = QSysInfo::currentCpuArchitecture();
    const bool arm = arch.contains("arm64") || arch.contains("aarch64");
#if defined(Q_OS_WIN)
    return arm ? QStringLiteral("windows-arm64") : QStringLiteral("windows-x64");
#elif defined(Q_OS_MACOS)
    return arm ? QStringLiteral("macos-arm64") : QStringLiteral("macos-x64");
#else
    return QStringLiteral("linux-x86_64");
#endif
}

bool assetMatchesPlatform(const QString& name)
{
    const auto lower = name.toLower();
    const auto suffix = platformAssetSuffix();
    if (suffix.isEmpty())
        return false;
    // Horizon's launcher assets are named like "horizon-launcher-setup.exe" or
    // "...-windows-x64.exe"; match loosely on the platform token plus a launcher token.
    const bool isLauncher = lower.contains(QStringLiteral("launcher"));
    if (!isLauncher)
        return false;
    if (suffix.startsWith(QStringLiteral("windows"))) {
        if (!lower.contains(QStringLiteral("win")))
            return false;
        return suffix.endsWith(QStringLiteral("arm64")) ? lower.contains(QStringLiteral("arm64"))
                                                       : !lower.contains(QStringLiteral("arm64"));
    }
    if (suffix.startsWith(QStringLiteral("macos"))) {
        if (!lower.contains(QStringLiteral("mac")))
            return false;
        return suffix.endsWith(QStringLiteral("arm64")) ? lower.contains(QStringLiteral("arm64"))
                                                       : !lower.contains(QStringLiteral("arm64"));
    }
    return lower.contains(QStringLiteral("linux")) || lower.endsWith(QStringLiteral(".appimage"));
}

}  // namespace

QString HorizonDialog::installDir()
{
    return FS::PathCombine(APPLICATION->dataDir(), QStringLiteral("horizon"));
}

HorizonDialog::HorizonDialog(QWidget* parent) : QDialog(parent)
{
    setWindowTitle(tr("Horizon"));
    resize(680, 460);

    auto* layout = new QVBoxLayout(this);

    auto* intro = new QLabel(this);
    intro->setWordWrap(true);
    intro->setText(tr("<b>Horizon</b> is a separate Rust reimplementation of Minecraft: Java Edition, "
                      "not a Minecraft instance. JL installs and launches the official Horizon launcher "
                      "for you; Horizon keeps its own mods (<code>.hnmod</code>) and resource packs.<br><br>"
                      "JL ships none of Horizon's code or assets. If you enjoy it, support its developers."));
    layout->addWidget(intro);

    m_status = new QLabel(tr("Not installed."), this);
    layout->addWidget(m_status);

    m_progress = new QProgressBar(this);
    m_progress->setVisible(false);
    layout->addWidget(m_progress);

    m_log = new QPlainTextEdit(this);
    m_log->setReadOnly(true);
    m_log->setMaximumBlockCount(400);
    layout->addWidget(m_log, 1);

    auto* buttons = new QHBoxLayout();
    buttons->addWidget(m_support = new QPushButton(tr("Support the developers"), this));
    buttons->addStretch(1);
    buttons->addWidget(m_check = new QPushButton(tr("Check for update"), this));
    buttons->addWidget(m_download = new QPushButton(tr("Install"), this));
    buttons->addWidget(m_run = new QPushButton(tr("Launch Horizon"), this));
    layout->addLayout(buttons);

    connect(m_support, &QPushButton::clicked, this, &HorizonDialog::openProjectPage);
    connect(m_check, &QPushButton::clicked, this, &HorizonDialog::checkForLauncher);
    connect(m_download, &QPushButton::clicked, this, &HorizonDialog::downloadLauncher);
    connect(m_run, &QPushButton::clicked, this, &HorizonDialog::runHorizon);

    resolveLocalLauncher();
    checkForLauncher();
}

void HorizonDialog::appendLog(const QString& line)
{
    m_log->appendPlainText(line);
}

void HorizonDialog::setBusy(bool busy)
{
    m_check->setEnabled(!busy);
    m_download->setEnabled(!busy);
    m_run->setEnabled(!busy && !m_launcherPath.isEmpty());
    m_progress->setVisible(busy);
    if (busy) {
        m_progress->setRange(0, 0);
    }
}

void HorizonDialog::resolveLocalLauncher()
{
    QDir dir(installDir());
    m_launcherPath.clear();
    if (!dir.exists())
        return;

    // Whatever executable the release shipped; Horizon's installer names differ per platform.
    const auto entries = dir.entryInfoList(QDir::Files | QDir::Executable);
    for (const auto& entry : entries) {
        const auto name = entry.fileName().toLower();
        if (name.contains(QStringLiteral("horizon")) &&
            (name.endsWith(QStringLiteral(".exe")) || name.endsWith(QStringLiteral(".appimage")) || !name.contains('.'))) {
            m_launcherPath = entry.absoluteFilePath();
            break;
        }
    }

    if (!m_launcherPath.isEmpty()) {
        m_status->setText(tr("Installed: %1").arg(m_launcherPath));
        m_run->setEnabled(true);
    } else {
        m_status->setText(tr("Not installed."));
        m_run->setEnabled(false);
    }
}

void HorizonDialog::openProjectPage()
{
    DesktopServices::openUrl(QUrl(kProjectUrl));
}

void HorizonDialog::checkForLauncher()
{
    setBusy(true);
    m_status->setText(tr("Checking for the latest Horizon launcher…"));

    auto job = new NetJob(QStringLiteral("Horizon release check"), APPLICATION->network());
    auto [request, response] = Net::Request::makeByteArray(QUrl(kReleasesApi));
    job->addNetAction(request);

    connect(job, &NetJob::succeeded, this, [this, response] {
        setBusy(false);
        const auto doc = QJsonDocument::fromJson(*response);
        if (!doc.isArray()) {
            fail(tr("GitHub did not return a release list."));
            return;
        }

        // Releases are newest first; the launcher builds are tagged/separate from the game.
        for (const auto& value : doc.array()) {
            const auto release = value.toObject();
            if (release.value("draft").toBool())
                continue;
            const auto assets = release.value("assets").toArray();
            for (const auto& assetValue : assets) {
                const auto asset = assetValue.toObject();
                const auto name = asset.value("name").toString();
                if (!assetMatchesPlatform(name))
                    continue;
                m_downloadUrl = asset.value("browser_download_url").toString();
                m_releaseTag = release.value("tag_name").toString();
                m_status->setText(tr("Latest Horizon launcher: %1 (%2)").arg(name, m_releaseTag));
                appendLog(tr("Found %1 in release %2").arg(name, m_releaseTag));
                m_download->setEnabled(true);
                return;
            }
        }

        fail(tr("No Horizon launcher build was found for this platform (%1).").arg(platformAssetSuffix()));
    });

    connect(job, &NetJob::failed, this, [this](QString reason) {
        setBusy(false);
        fail(tr("Could not reach GitHub: %1").arg(reason));
    });

    job->start();
}

void HorizonDialog::downloadLauncher()
{
    if (m_downloadUrl.isEmpty()) {
        fail(tr("Check for an update first."));
        return;
    }

    if (!FS::ensureFolderPathExists(installDir())) {
        fail(tr("Could not create %1").arg(installDir()));
        return;
    }

    // Keep the extension from the URL so Windows knows it is an installer.
    const QUrl url(m_downloadUrl);
    auto fileName = url.fileName();
    if (fileName.isEmpty())
        fileName = platformAssetSuffix() + QStringLiteral(".bin");
    const auto target = FS::PathCombine(installDir(), fileName);

    setBusy(true);
    m_status->setText(tr("Downloading %1…").arg(fileName));

    auto job = new NetJob(QStringLiteral("Horizon launcher download"), APPLICATION->network());
    auto download = Net::Request::makeFile(url, target);
    job->addNetAction(download);

    connect(job, &NetJob::succeeded, this, [this, target] {
        setBusy(false);
        appendLog(tr("Saved to %1").arg(target));
        resolveLocalLauncher();
        if (m_launcherPath.isEmpty()) {
            // An installer: hand it to the OS rather than pretending JL can run it in place.
            appendLog(tr("Launching the Horizon installer…"));
            QDesktopServices::openUrl(QUrl::fromLocalFile(target));
            m_status->setText(tr("Run the Horizon installer, then press “Check for update”."));
        } else {
            m_status->setText(tr("Installed: %1").arg(m_launcherPath));
        }
    });

    connect(job, &NetJob::failed, this, [this](QString reason) {
        setBusy(false);
        fail(tr("Download failed: %1").arg(reason));
    });

    job->start();
}

void HorizonDialog::runHorizon()
{
    if (m_launcherPath.isEmpty()) {
        fail(tr("Horizon is not installed yet."));
        return;
    }

    // Horizon is its own program; JL starts it with the same data folder it manages.
    auto* process = new QProcess(this);
    process->setProgram(m_launcherPath);
    process->setWorkingDirectory(installDir());
    connect(process, &QProcess::started, this, [this] { appendLog(tr("Horizon started.")); });
    connect(process, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError) { fail(tr("Could not start %1").arg(m_launcherPath)); });
    connect(process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this,
            [this, process](int code, QProcess::ExitStatus) {
                appendLog(tr("Horizon exited with code %1.").arg(code));
                process->deleteLater();
            });
    process->start();
}

void HorizonDialog::fail(const QString& reason)
{
    appendLog(reason);
    m_status->setText(reason);
}
