// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonResources.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>

#include "Application.h"
#include "FileSystem.h"
#include "archive/ExtractZipTask.h"
#include "minecraft/HorizonBuilds.h"
#include "net/NetJob.h"
#include "net/Request.h"

// ---------------------------------------------------------------------------------------
// Prepared resources
// ---------------------------------------------------------------------------------------

namespace HorizonResources {

QString preparedRoot()
{
    return FS::PathCombine(APPLICATION->dataRoot(), QStringLiteral("horizon"), QStringLiteral("prepared"));
}

QString preparedDir(const QString& tag, const QString& minecraftVersion)
{
    // Join with a character neither part can contain, so "nightly" + "26.3" cannot collide with
    // a tag that happens to look like "nightly-26.3".
    return FS::PathCombine(preparedRoot(), QStringLiteral("%1__%2").arg(tag, minecraftVersion));
}

bool isPrepared(const QString& dir)
{
    if (dir.isEmpty())
        return false;
    // horizon-prepare writes research-lock.json and the resource tree together; a folder with
    // only one of them is a prepare that stopped.
    return QFileInfo::exists(FS::PathCombine(dir, QStringLiteral("research-lock.json")));
}

QString newestPrepared()
{
    const QDir root(preparedRoot());
    if (!root.exists())
        return {};

    QString best;
    QDateTime bestDate;
    for (const auto& name : root.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        const auto dir = FS::PathCombine(preparedRoot(), name);
        if (!isPrepared(dir))
            continue;
        const auto when = QFileInfo(dir).lastModified();
        if (best.isEmpty() || when > bestDate) {
            best = dir;
            bestDate = when;
        }
    }
    return best;
}

}  // namespace HorizonResources

// ---------------------------------------------------------------------------------------
// Download one build
// ---------------------------------------------------------------------------------------

HorizonDownloadTask::HorizonDownloadTask(QString tag, QWidget* parent) : m_tag(std::move(tag))
{
    Q_UNUSED(parent)
    if (m_tag.isEmpty())
        m_tag = HorizonBuilds::kNightlyTag;
}

void HorizonDownloadTask::executeTask()
{
    if (HorizonBuilds::platformAsset().isEmpty()) {
        fail(tr("Horizon has no build for this platform."));
        return;
    }
    setStatus(tr("Looking up the newest Horizon build…"));
    resolveRelease();
}

void HorizonDownloadTask::resolveRelease()
{
    // Ask GitHub for the tag we want directly. `nightly` is a moving tag, so this always gets
    // the newest build; a dated nightly-<date> tag disappears after seven days, which is why it
    // is never stored as a pin.
    auto url = QUrl(QStringLiteral("%1/tags/%2").arg(HorizonBuilds::kReleasesApi, m_tag));
    auto [request, response] = Net::Request::makeByteArray(url);

    auto job = new NetJob(QStringLiteral("Horizon build lookup"), APPLICATION->network());
    job->addNetAction(request);
    connect(job, &NetJob::succeeded, this, [this, response, job] {
        job->deleteLater();
        const auto doc = QJsonDocument::fromJson(*response);
        if (!doc.isObject()) {
            fail(tr("GitHub returned something that is not a release."));
            return;
        }
        const auto release = doc.object();

        // The tag GitHub actually served, so "nightly" is recorded as the real release.
        const auto resolvedTag = release.value("tag_name").toString();
        if (!resolvedTag.isEmpty())
            m_tag = resolvedTag;

        const auto assetName = HorizonBuilds::platformAsset();
        for (const auto& value : release.value("assets").toArray()) {
            const auto asset = value.toObject();
            if (asset.value("name").toString() != assetName)
                continue;
            const auto downloadUrl = QUrl(asset.value("browser_download_url").toString());
            if (!downloadUrl.isValid()) {
                fail(tr("The release has no download URL for %1.").arg(assetName));
                return;
            }
            downloadArchive(downloadUrl);
            return;
        }
        fail(tr("The Horizon release %1 has no %2 asset.").arg(m_tag, assetName));
    });
    connect(job, &NetJob::failed, this, [this, job](QString reason) {
        job->deleteLater();
        fail(tr("Could not reach GitHub: %1").arg(reason));
    });
    job->start();
}

void HorizonDownloadTask::downloadArchive(const QUrl& url)
{
    const auto target = HorizonBuilds::buildDir(m_tag);
    if (!FS::ensureFolderPathExists(target)) {
        fail(tr("Could not create %1").arg(target));
        return;
    }

    m_archivePath = FS::PathCombine(target, url.fileName());
    setStatus(tr("Downloading Horizon %1…").arg(m_tag));

    auto job = new NetJob(QStringLiteral("Horizon build download"), APPLICATION->network());
    auto request = Net::Request::makeFile(url, m_archivePath);
    job->addNetAction(request);
    connect(job, &NetJob::succeeded, this, [this, job] {
        job->deleteLater();
        unpackArchive();
    });
    connect(job, &NetJob::failed, this, [this, job](QString reason) {
        job->deleteLater();
        fail(tr("Download failed: %1").arg(reason));
    });
    job->start();
}

void HorizonDownloadTask::unpackArchive()
{
    setStatus(tr("Unpacking Horizon %1…").arg(m_tag));

    const auto target = HorizonBuilds::buildDir(m_tag);
    auto* extract = new MMCZip::ExtractZipTask(m_archivePath, QDir(target));
    connect(extract, &Task::succeeded, this, [this, extract] {
        extract->deleteLater();
        // The archive served its purpose; keeping it only wastes 30 MB per build.
        QFile::remove(m_archivePath);

        if (!HorizonBuilds::isComplete(HorizonBuilds::buildDir(m_tag))) {
            fail(tr("The Horizon archive did not contain horizon-client, horizon-prepare and "
                    "research-lock.json. JL will not run a partial build."));
            return;
        }
        emitSucceeded();
    });
    connect(extract, &Task::failed, this, [this, extract](const QString& reason) {
        extract->deleteLater();
        fail(tr("Could not unpack the Horizon archive: %1").arg(reason));
    });
    extract->start();
}

void HorizonDownloadTask::fail(const QString& reason)
{
    emit logLine(reason);
    emitFailed(reason);
}

// ---------------------------------------------------------------------------------------
// Prepare resources
// ---------------------------------------------------------------------------------------

HorizonPrepareTask::HorizonPrepareTask(QString buildDir, QString outputDir, QWidget* parent)
    : m_buildDir(std::move(buildDir)), m_outputDir(std::move(outputDir))
{
    Q_UNUSED(parent)
}

void HorizonPrepareTask::executeTask()
{
    const auto prepare = HorizonBuilds::preparePath(m_buildDir);
    if (prepare.isEmpty()) {
        emitFailed(tr("This Horizon build has no horizon-prepare, so its resources cannot be built."));
        return;
    }
    if (!FS::ensureFolderPathExists(m_outputDir)) {
        emitFailed(tr("Could not create %1").arg(m_outputDir));
        return;
    }

    m_process = new QProcess(this);
    m_process->setProgram(prepare);
    m_process->setWorkingDirectory(m_buildDir);
    m_process->setProcessChannelMode(QProcess::SeparateChannels);

    // Horizon's documented preparation call. --complete copies the sounds and fails unless the
    // result would pass --check, so the game starts with nothing missing.
    m_process->setArguments({ "--prepare", "--output", m_outputDir, "--complete", "--progress", "json" });

    connect(m_process, &QProcess::readyReadStandardOutput, this, &HorizonPrepareTask::onReadyRead);
    connect(m_process, qOverload<int, QProcess::ExitStatus>(&QProcess::finished), this, &HorizonPrepareTask::onFinished);
    connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            emitFailed(tr("Could not start horizon-prepare: %1").arg(m_process->errorString()));
    });

    setStatus(tr("Preparing Horizon resources from your Minecraft files…"));
    m_process->start();
}

void HorizonPrepareTask::onReadyRead()
{
    if (!m_process)
        return;
    m_logBuffer += QString::fromLocal8Bit(m_process->readAllStandardOutput());

    // --progress json emits one JSON object per line: {"message"}, {"fraction"}, {"error"}.
    int newline;
    while ((newline = m_logBuffer.indexOf('\n')) >= 0) {
        const auto line = m_logBuffer.left(newline).trimmed();
        m_logBuffer.remove(0, newline + 1);
        if (line.isEmpty())
            continue;

        const auto doc = QJsonDocument::fromJson(line.toUtf8());
        if (!doc.isObject()) {
            emit logLine(line);
            continue;
        }
        const auto object = doc.object();
        if (object.contains("message")) {
            emit logLine(object.value("message").toString());
        } else if (object.contains("fraction")) {
            // 0..1, never decreasing; the progress bar wants whole numbers.
            const auto fraction = object.value("fraction").toDouble();
            setProgress(static_cast<qint64>(fraction * 1000), 1000);
        } else if (object.contains("error")) {
            m_logBuffer = object.value("error").toString();
        }
    }
}

void HorizonPrepareTask::onFinished(int exitCode)
{
    if (!m_process)
        return;
    onReadyRead();
    m_process->deleteLater();
    m_process = nullptr;

    if (exitCode == 0) {
        emitSucceeded();
        return;
    }
    // horizon-prepare's own contract: 1 failed or gaps found, 2 refused command line.
    const auto detail = m_logBuffer.trimmed().isEmpty() ? tr("no detail was printed") : m_logBuffer.trimmed();
    emitFailed(tr("Horizon could not prepare its resources: %1").arg(detail));
}

// ---------------------------------------------------------------------------------------
// Keep the build current before a launch
// ---------------------------------------------------------------------------------------

HorizonUpdateTask::HorizonUpdateTask(QString currentTag, QWidget* parent)
    : m_currentTag(std::move(currentTag)), m_parent(parent)
{}

void HorizonUpdateTask::executeTask()
{
    setStatus(tr("Checking for a newer Horizon build…"));
    checkNewest();
}

void HorizonUpdateTask::checkNewest()
{
    // `nightly` is a moving tag, so asking for it always names the newest build. Cheaper than
    // listing every release: one request, one object.
    auto url = QUrl(QStringLiteral("%1/tags/%2").arg(HorizonBuilds::kReleasesApi, HorizonBuilds::kNightlyTag));
    auto [request, response] = Net::Request::makeByteArray(url);

    auto job = new NetJob(QStringLiteral("Horizon update check"), APPLICATION->network());
    job->addNetAction(request);
    connect(job, &NetJob::succeeded, this, [this, response, job] {
        job->deleteLater();
        const auto doc = QJsonDocument::fromJson(*response);
        if (!doc.isObject()) {
            // An update check that cannot run must never block a launch: the build already
            // installed still works.
            emit logLine(tr("Could not read Horizon's release information; starting the installed build."));
            emitSucceeded();
            return;
        }
        const auto tag = doc.object().value("tag_name").toString();
        if (tag.isEmpty()) {
            emitSucceeded();
            return;
        }
        if (tag == m_currentTag) {
            emit logLine(tr("Horizon %1 is the newest build.").arg(tag));
            emitSucceeded();
            return;
        }
        if (HorizonBuilds::isComplete(HorizonBuilds::buildDir(tag))) {
            // Already downloaded by an earlier launch or instance; just switch to it.
            emit logLine(tr("Horizon %1 is already installed; using it.").arg(tag));
            m_newTag = tag;
            m_updated = true;
            emitSucceeded();
            return;
        }

        emit logLine(tr("A newer Horizon build is available: %1 (installed: %2). Updating…")
                         .arg(tag, m_currentTag.isEmpty() ? tr("none") : m_currentTag));

        auto* download = new HorizonDownloadTask(tag, m_parent);
        connect(download, &HorizonDownloadTask::logLine, this, [this](QString line) { emit logLine(line); });
        connect(download, &Task::succeeded, this, [this, download] {
            m_newTag = download->installedTag();
            m_updated = true;
            download->deleteLater();
            emitSucceeded();
        });
        connect(download, &Task::failed, this, [this, download](const QString& reason) {
            download->deleteLater();
            // Same rule as above: a failed update must not stop the installed build from starting.
            emit logLine(tr("The update failed (%1); starting the installed build instead.").arg(reason));
            emitSucceeded();
        });
        download->start();
    });
    connect(job, &NetJob::failed, this, [this, job](QString reason) {
        job->deleteLater();
        emit logLine(tr("Could not check for a Horizon update (%1); starting the installed build.").arg(reason));
        emitSucceeded();
    });
    job->start();
}

void HorizonUpdateTask::fail(const QString& reason)
{
    emit logLine(reason);
    emitFailed(reason);
}
