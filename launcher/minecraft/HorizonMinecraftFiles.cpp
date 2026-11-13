// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonMinecraftFiles.h"

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>

#include "Application.h"
#include "settings/SettingsObject.h"
#include "FileSystem.h"

namespace HorizonMinecraftFiles {

namespace {

QString exeName(const QString& base)
{
#if defined(Q_OS_WIN)
    return base + QStringLiteral(".exe");
#else
    return base;
#endif
}

/// \brief Roots to look in, most specific first.
///
/// The user's explicit choice wins. Otherwise JL's data root, which is also the process working
/// directory (Application sets it), so QDir::current() is the same thing.
QStringList roots()
{
    QStringList out;
    const auto override = APPLICATION->settings()->get("HorizonMinecraftDir").toString();
    if (!override.isEmpty())
        out << override;
    const auto current = QDir::current().absolutePath();
    if (!out.contains(current))
        out << current;
    return out;
}

/// \brief A version JSON: Prism keeps it under meta/, next to the launcher's other index files.
QString findVersionJson(const QString& root, const QString& version)
{
    // This is the one that was wrong before: Horizon's own error says
    // ".minecraft/versions/26.3/26.3.json", so that shape was copied blindly. Prism writes
    // <dataRoot>/meta/net.minecraft/<version>.json (Meta::BaseEntity::executeTask uses
    // QDir("meta").absoluteFilePath(localFilename())). The others are fallbacks only.
    const QStringList candidates = {
        FS::PathCombine(root, QStringLiteral("meta"), QStringLiteral("net.minecraft"), version + QStringLiteral(".json")),
        FS::PathCombine(root, QStringLiteral("net.minecraft"), version + QStringLiteral(".json")),
        FS::PathCombine(FS::PathCombine(root, QStringLiteral("versions")), version, version + QStringLiteral(".json")),
        FS::PathCombine(FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("versions")), version, version + QStringLiteral(".json")),
    };
    for (const auto& candidate : candidates) {
        if (QFileInfo::exists(candidate))
            return candidate;
    }
    return {};
}

/// \brief The vanilla client jar, for a version Prism downloaded through its own meta.
QString findClientJar(const QStringList& roots, const QString& version)
{
    for (const auto& root : roots) {
        const QStringList candidates = {
            FS::PathCombine(root, QStringLiteral("meta"), QStringLiteral("net.minecraft"), version + QStringLiteral(".jar")),
            FS::PathCombine(root, QStringLiteral("net.minecraft"), version + QStringLiteral(".jar")),
            FS::PathCombine(FS::PathCombine(root, QStringLiteral("versions")), version, version + QStringLiteral(".jar")),
            FS::PathCombine(FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("versions")), version, version + QStringLiteral(".jar")),
        };
        for (const auto& candidate : candidates) {
            if (QFileInfo::exists(candidate))
                return candidate;
        }
    }
    return {};
}

}  // namespace

Located locate(MinecraftInstance* instance, const QString& minecraftVersion)
{
    Q_UNUSED(instance)
    Located out;
    out.version = minecraftVersion;

    const auto searchRoots = roots();

    // 1. The version JSON on disk.
    for (const auto& root : searchRoots) {
        out.versionJson = findVersionJson(root, minecraftVersion);
        if (!out.versionJson.isEmpty())
            break;
    }
    if (out.versionJson.isEmpty()) {
        for (const auto& root : searchRoots)
            out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "%1/meta/net.minecraft/%2.json")
                                .arg(root, minecraftVersion);
    }

    // 2. The client jar. Prism downloads the vanilla client through its meta cache; it is not
    //    kept as <version>.jar beside the JSON in every case, so this is allowed to be empty and
    //    the caller falls back to naming only what it found.
    out.clientJar = findClientJar(searchRoots, minecraftVersion);
    if (out.clientJar.isEmpty()) {
        for (const auto& root : searchRoots)
            out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "%1/meta/net.minecraft/%2.jar")
                                .arg(root, minecraftVersion);
    }

    // 3. Libraries and assets: shared by every instance, one copy each.
    for (const auto& root : searchRoots) {
        const auto dir = FS::PathCombine(root, QStringLiteral("libraries"));
        if (QDir(dir).exists()) {
            out.librariesDir = dir;
            break;
        }
    }
    if (out.librariesDir.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "libraries: %1/libraries").arg(searchRoots.value(0));

    for (const auto& root : searchRoots) {
        const auto dir = FS::PathCombine(root, QStringLiteral("assets"));
        if (QDir(dir).exists()) {
            out.assetsDir = dir;
            break;
        }
    }
    if (out.assetsDir.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "assets: %1/assets").arg(searchRoots.value(0));

    return out;
}

QStringList prepareArguments(const Located& files)
{
    if (!files.complete())
        return {};

    // Horizon documents these four for "a launcher whose files aren't laid out like the official
    // launcher's, each names what --minecraft-dir would give".
    QStringList args;
    if (!files.versionJson.isEmpty())
        args << QStringLiteral("--version-json") << files.versionJson;
    if (!files.clientJar.isEmpty())
        args << QStringLiteral("--client-jar") << files.clientJar;
    if (!files.librariesDir.isEmpty())
        args << QStringLiteral("--libraries-dir") << files.librariesDir;
    if (!files.assetsDir.isEmpty())
        args << QStringLiteral("--assets-dir") << files.assetsDir;
    return args;
}

QString explain(const Located& files)
{
    // Never dump a wall of "C:/x/y/z; C:/a/b/c" at someone: say plainly what a folder is, or what
    // it is missing and where the real one is.
    if (files.complete())
        return {};

    QStringList missing;
    if (files.versionJson.isEmpty())
        missing << QCoreApplication::translate("HorizonMinecraftFiles", "the version file for Minecraft %1").arg(files.version);
    if (files.clientJar.isEmpty())
        missing << QCoreApplication::translate("HorizonMinecraftFiles", "the client jar");
    if (files.librariesDir.isEmpty())
        missing << QCoreApplication::translate("HorizonMinecraftFiles", "libraries/");
    if (files.assetsDir.isEmpty())
        missing << QCoreApplication::translate("HorizonMinecraftFiles", "assets/");

    return QCoreApplication::translate("HorizonMinecraftFiles", "Missing %1").arg(missing.join(QStringLiteral(", ")));
}

}  // namespace HorizonMinecraftFiles
