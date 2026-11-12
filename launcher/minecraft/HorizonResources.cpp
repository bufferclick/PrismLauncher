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

namespace {
/// Pages walked when the direct `nightly` tag lookup fails: the releases list is led by a
/// `launcher@x.y.z` entry several times a day, so a Nightly is often not on page 1.
constexpr int kMaxReleasePages = 10;
constexpr int kReleasesPerPage = 100;
}  // namespace

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
    if (QDir(target).exists() && !HorizonBuilds::isComplete(target)) {
        // Left behind by an earlier, broken unpack. Remove it, or every retry would unpack on
        // top of a folder that can never pass the check.
        emit logLine(tr("Discarding an unusable earlier download at %1").arg(target));
        if (!FS::deletePath(target)) {
            fail(tr("Could not clear the broken download at %1. Delete it by hand and retry.").arg(target));
            return;
        }
    }
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
            // Name what is actually there: a wrong-layout archive is otherwise impossible to
            // diagnose from the outside, which is exactly how the first attempt went wrong.
            const auto dir = HorizonBuilds::buildDir(m_tag);
            const auto root = HorizonBuilds::rootOf(dir);
            const auto found = QDir(root).entryList(QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot).join(QStringLiteral(", "));
            fail(tr("The Horizon archive was unpacked to %1 but is not a usable build: it needs "
                    "horizon-client, horizon-prepare and exporters/manifest.json. What is there: %2")
                     .arg(root, found.isEmpty() ? tr("nothing") : found));
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
    // The preparer reads research-lock.json and exporters/ from beside its own binary, which the
    // archive nests one level below the unpack folder.
    m_process->setWorkingDirectory(HorizonBuilds::rootOf(m_buildDir));
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
    // Cheap and exact: ask for the moving `nightly` tag itself. The repository also publishes a
    // `launcher@x.y.z` release several times a day, which pushes the Nightlies off the first
    // page of the releases list -- but a direct tag lookup never pages, so it cannot be hidden.
    auto url = QUrl(QStringLiteral("%1/tags/%2").arg(HorizonBuilds::kReleasesApi, HorizonBuilds::kNightlyTag));
    auto [request, response] = Net::Request::makeByteArray(url);

    auto job = new NetJob(QStringLiteral("Horizon update check"), APPLICATION->network());
    job->addNetAction(request);
    connect(job, &NetJob::succeeded, this, [this, response, job] {
        job->deleteLater();
        const auto doc = QJsonDocument::fromJson(*response);
        if (!doc.isObject()) {
            emit logLine(tr("Could not read Horizon's release information; starting the installed build."));
            emitSucceeded();
            return;
        }
        const auto tag = doc.object().value("tag_name").toString();
        if (tag.isEmpty()) {
            emit logLine(tr("Horizon's nightly release had no tag; starting the installed build."));
            emitSucceeded();
            return;
        }
        considerTag(tag);
    });
    // A tag lookup can 404 if the nightly was withdrawn. Fall back to scanning the release list,
    // which is paginated, rather than concluding there is nothing newer.
    connect(job, &NetJob::failed, this, [this, job](QString reason) {
        job->deleteLater();
        emit logLine(tr("Could not look up Horizon's nightly release (%1); scanning the release list.").arg(reason));
        scanPage(1);
    });
    job->start();
}

void HorizonUpdateTask::scanPage(int page)
{
    // The release list is newest-first but commonly led by many `launcher@x.y.z` entries, so a
    // Nightly can be several pages down. Walk pages until one is found; the launch is never
    // blocked if they run out.
    if (page > kMaxReleasePages) {
        emit logLine(tr("No Horizon nightly build was found in the newest %1 releases; starting the "
                        "installed build.")
                         .arg(kMaxReleasePages * kReleasesPerPage));
        emitSucceeded();
        return;
    }

    auto url = QUrl(QStringLiteral("%1?per_page=%2&page=%3")
                        .arg(HorizonBuilds::kReleasesApi)
                        .arg(kReleasesPerPage)
                        .arg(page));
    auto [request, response] = Net::Request::makeByteArray(url);

    auto job = new NetJob(QStringLiteral("Horizon release scan"), APPLICATION->network());
    job->addNetAction(request);
    connect(job, &NetJob::succeeded, this, [this, response, job, page] {
        job->deleteLater();
        const auto doc = QJsonDocument::fromJson(*response);
        if (!doc.isArray()) {
            emitSucceeded();
            return;
        }
        const auto releases = doc.array();
        if (releases.isEmpty()) {
            // Ran past the end of the list without finding a Nightly.
            emit logLine(tr("No Horizon nightly build was found; starting the installed build."));
            emitSucceeded();
            return;
        }

        // Prefer the moving `nightly` tag when it is on the page: a dated `nightly-<date>` tag is
        // deleted after seven days, so it must never become the pinned choice while `nightly`
        // exists. Everything tagged `nightly*` is a real game-files release either way.
        QString dated;
        for (const auto& value : releases) {
            const auto tag = value.toObject().value("tag_name").toString();
            if (tag == HorizonBuilds::kNightlyTag) {
                considerTag(tag);
                return;
            }
            if (dated.isEmpty() && tag.startsWith(QStringLiteral("nightly")))
                dated = tag;
        }
        if (!dated.isEmpty()) {
            considerTag(dated);
            return;
        }
        scanPage(page + 1);
    });
    connect(job, &NetJob::failed, this, [this, job, page](QString reason) {
        job->deleteLater();
        if (page < kMaxReleasePages) {
            scanPage(page + 1);
            return;
        }
        emit logLine(tr("Could not check for a Horizon update (%1); starting the installed build.").arg(reason));
        emitSucceeded();
    });
    job->start();
}

void HorizonUpdateTask::considerTag(const QString& tag)
{
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
        // A failed update must not stop the installed build from starting.
        emit logLine(tr("The update failed (%1); starting the installed build instead.").arg(reason));
        emitSucceeded();
    });
    download->start();
}

void HorizonUpdateTask::fail(const QString& reason)
{
    emit logLine(reason);
    emitFailed(reason);
}
