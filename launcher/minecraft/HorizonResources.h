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

#include <QDateTime>
#include <QString>
#include <QUrl>

#include "tasks/Task.h"

class QProcess;
class QWidget;

/**
 * Prepared game resources.
 *
 * Horizon contains none of Minecraft's code, textures or sounds: horizon-prepare reads them from
 * the player's own Minecraft installation and writes a folder that horizon-client reads with
 * --resources. One prepared folder serves every instance of that build, because the resources
 * depend on the build and the Minecraft version, not on the instance.
 */
namespace HorizonResources {

/// \brief Root of every prepared set: <dataRoot>/horizon/prepared.
QString preparedRoot();

/// \brief The folder for one build tag and Minecraft version.
QString preparedDir(const QString& tag, const QString& minecraftVersion);

/// \brief The newest prepared folder that is complete, or empty.
QString newestPrepared();

/// \brief True when this folder looks written by a successful prepare.
bool isPrepared(const QString& dir);

}  // namespace HorizonResources

/**
 * Downloads one Horizon build and unpacks it.
 *
 * Per Horizon's launch guide, a build is one archive per platform from a GitHub release of
 * horizon-rust/horizon, holding horizon-client, horizon-prepare, research-lock.json and
 * exporters/. The newest is the release tagged `nightly`.
 */
class HorizonDownloadTask : public Task {
    Q_OBJECT

   public:
    /// \brief downloads the newest build, or a specific tag when one is given.
    explicit HorizonDownloadTask(QString tag = QString(), QWidget* parent = nullptr);

    /// \brief The tag that ended up being installed (after resolving "nightly").
    QString installedTag() const { return m_tag; }

    void executeTask() override;

   signals:
    /// \brief Human-readable progress, for the dialog that started this.
    void logLine(QString line);

   private:
    void resolveRelease();
    void downloadArchive(const QUrl& url);
    void unpackArchive();
    void fail(const QString& reason);

    QString m_tag;
    QString m_archivePath;
};

/**
 * Keeps the build current before a launch.
 *
 * Horizon publishes a new `nightly` build every few hours. This resolves that tag and, when the
 * running build is older, downloads and unpacks the new one. The old folder is kept, so a build
 * that misbehaves can be pinned back; Horizon's guide asks for exactly that.
 */
class HorizonUpdateTask : public Task {
    Q_OBJECT

   public:
    explicit HorizonUpdateTask(QString currentTag, QWidget* parent = nullptr);

    /// \brief True when a newer build was installed by this run.
    bool updated() const { return m_updated; }
    /// \brief The tag now installed (the old one when nothing changed).
    QString installedTag() const { return m_newTag.isEmpty() ? m_currentTag : m_newTag; }

    void executeTask() override;

   signals:
    void logLine(QString line);

   private:
    void checkNewest();
    void scanPage(int page);
    void considerTag(const QString& tag);
    void fail(const QString& reason);

    QString m_currentTag;
    QString m_newTag;
    bool m_updated = false;
    QWidget* m_parent;
};

/**
 * Fetches the server jar the first prepare needs.
 *
 * horizon-prepare documents that the first --prepare needs --server-jar, that Horizon never
 * downloads it, and that the launcher must fetch it from the version JSON's downloads.server for
 * an owner only. JL already has the version JSON, so it can do exactly that.
 */
class HorizonServerJarTask : public Task {
    Q_OBJECT

   public:
    explicit HorizonServerJarTask(QString versionJsonPath, QString outputPath);

    /// \brief The downloaded jar, when it succeeded.
    QString jarPath() const { return m_outputPath; }
    /// \brief True when there was no server download to fetch (nothing to do, not an error).
    bool notAvailable() const { return m_notAvailable; }

    void executeTask() override;

   signals:
    /// \brief Human-readable progress, for the dialog that started this.
    void logLine(QString line);

   private:
    QString m_versionJsonPath;
    QString m_outputPath;
    bool m_notAvailable = false;
};

/**
 * Makes sure JL has the vanilla version JSON for a Minecraft version.
 *
 * The preparer needs a version JSON, and JL only keeps one for versions an instance has
 * actually installed. Rather than tell someone to go play 26.3 in another launcher, this asks
 * Mojang's version manifest for the version and saves it where JL reads meta from, so the rest
 * of the pipeline works from JL's own copy.
 */
class HorizonVersionJsonTask : public Task {
    Q_OBJECT

   public:
    explicit HorizonVersionJsonTask(QString minecraftVersion, QString outputPath);

    void executeTask() override;

   signals:
    void logLine(QString line);

   private:
    QString m_version;
    QString m_outputPath;
};

/**
 * Runs horizon-prepare to build the resources horizon-client reads.
 *
 * This is the step Horizon will not do without: it needs the player's own Minecraft files and a
 * Java of the pinned version, and it checks every file against research-lock.json.
 */
class HorizonPrepareTask : public Task {
    Q_OBJECT

   public:
    HorizonPrepareTask(QString buildDir, QString outputDir, QWidget* parent = nullptr);

    void executeTask() override;

   signals:
    /// \brief Human-readable progress, for the dialog that started this.
    void logLine(QString line);

   private:
    void fetchServerJarThenPrepare();
    void startPreparer();
    QString serverJarPath() const;
    void onReadyRead();
    void onFinished(int exitCode);

    QString m_buildDir;
    QString m_outputDir;
    QProcess* m_process = nullptr;
    QString m_logBuffer;
};
