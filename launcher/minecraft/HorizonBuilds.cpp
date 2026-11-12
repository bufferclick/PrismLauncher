// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonBuilds.h"

#include <QDir>
#include <QFileInfo>
#include <QSysInfo>
#include <QStringList>

#include "Application.h"
#include "FileSystem.h"

namespace HorizonBuilds {

QString platformAsset()
{
    // Runtime check, not a compile-time macro: Q_PROCESSOR_ARM_64 is not set by every Qt build,
    // and Windows on ARM runs the x64 launcher too.
    const auto arch = QSysInfo::currentCpuArchitecture();
    const bool arm = arch.contains(QStringLiteral("arm64")) || arch.contains(QStringLiteral("aarch64"));
#if defined(Q_OS_WIN)
    return arm ? QStringLiteral("horizon-windows-arm64.zip") : QStringLiteral("horizon-windows-x64.zip");
#elif defined(Q_OS_MACOS)
    return arm ? QStringLiteral("horizon-macos-arm64.zip") : QStringLiteral("horizon-macos-x64.zip");
#else
    // Horizon publishes Linux as .tar.gz, which JL cannot unpack yet. Returning empty makes the
    // download refuse cleanly with a message, instead of saving a tarball and failing later.
    return {};
#endif
}

QString buildsRoot()
{
    return FS::PathCombine(APPLICATION->dataRoot(), QStringLiteral("horizon"));
}

QString buildDir(const QString& tag)
{
    return FS::PathCombine(buildsRoot(), tag);
}

static QString exeName(const QString& base)
{
#if defined(Q_OS_WIN)
    return base + QStringLiteral(".exe");
#else
    return base;
#endif
}

QString clientPath(const QString& dir)
{
    const auto path = FS::PathCombine(dir, exeName(QStringLiteral("horizon-client")));
    return QFileInfo::exists(path) ? path : QString();
}

QString preparePath(const QString& dir)
{
    const auto path = FS::PathCombine(dir, exeName(QStringLiteral("horizon-prepare")));
    return QFileInfo::exists(path) ? path : QString();
}

bool isComplete(const QString& dir)
{
    if (dir.isEmpty())
        return false;
    // A build is only usable whole: the guide says client, preparer, research-lock.json and
    // exporters/ work together, so half an unpack is not a build.
    return !clientPath(dir).isEmpty() && !preparePath(dir).isEmpty() &&
           QFileInfo::exists(FS::PathCombine(dir, QStringLiteral("research-lock.json")));
}

QString newestInstalledTag()
{
    const QDir root(buildsRoot());
    if (!root.exists())
        return {};

    QString best;
    QDateTime bestDate;
    for (const auto& tag : root.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        const auto dir = buildDir(tag);
        if (!isComplete(dir))
            continue;
        // Sort by when JL unpacked it: nightly tags carry a date, stables do not sort sanely
        // as strings ("v0.2.9" vs "v0.2.10").
        const auto when = QFileInfo(dir).lastModified();
        if (best.isEmpty() || when > bestDate) {
            best = tag;
            bestDate = when;
        }
    }
    return best;
}

}  // namespace HorizonBuilds
