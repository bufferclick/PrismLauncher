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
#include "FileSystem.h"

namespace HorizonMinecraftFiles {

namespace {

/// \brief The client jar for a version, in Prism's shared meta layout.
QString jarInMeta(const QString& version)
{
    // Prism stores the client jar beside the version JSON when it was downloaded as a file:
    // <dataRoot>/net.minecraft/<version>.jar. The official layout pairs them under versions/.
    const auto root = QDir::current().absolutePath();
    const QStringList candidates = {
        FS::PathCombine(root, QStringLiteral("net.minecraft"), version + QStringLiteral(".jar")),
        FS::PathCombine(root, QStringLiteral("versions"), version, version + QStringLiteral(".jar")),
        FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("versions"), version, version + QStringLiteral(".jar")),
    };
    for (const auto& candidate : candidates) {
        if (QFileInfo::exists(candidate))
            return candidate;
    }
    return {};
}

QString versionJsonInMeta(const QString& version)
{
    const auto root = QDir::current().absolutePath();
    // Prism's shared meta: <dataRoot>/net.minecraft/<version>.json. The others cover an instance
    // folder that kept its own copy, or a data root laid out like the official launcher.
    const QStringList candidates = {
        FS::PathCombine(root, QStringLiteral("net.minecraft"), version + QStringLiteral(".json")),
        FS::PathCombine(root, QStringLiteral("versions"), version, version + QStringLiteral(".json")),
        FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("versions"), version, version + QStringLiteral(".json")),
    };
    for (const auto& candidate : candidates) {
        if (QFileInfo::exists(candidate))
            return candidate;
    }
    return {};
}

}  // namespace

Located locate(MinecraftInstance* instance, const QString& minecraftVersion)
{
    Q_UNUSED(instance)
    Located out;
    out.version = minecraftVersion;

    // An explicit folder wins: Settings → Horizon lets someone point at a Prism/MultiMC data
    // root or an official .minecraft when JL's own copy is not the one they want used.
    const auto override = APPLICATION->settings()->get("HorizonMinecraftDir").toString();
    const auto root = override.isEmpty() ? QDir::current().absolutePath() : override;

    // 1. The version JSON, in Prism's shared meta layout. This is the file JL downloaded and
    //    launches the instance from; it is not under .minecraft/versions, which is why Horizon
    //    could not find it.
    if (out.versionJson.isEmpty())
        out.versionJson = versionJsonInMeta(minecraftVersion);
    if (out.versionJson.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "version JSON: %1/net.minecraft/%2.json").arg(root, minecraftVersion);

    // 2. The client jar.
    out.clientJar = jarInMeta(minecraftVersion);
    if (out.clientJar.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "client jar: %1/net.minecraft/%2.jar").arg(root, minecraftVersion);

    // 3. Libraries and assets. Prism keeps both once, shared by every instance.
    for (const auto& candidate : { FS::PathCombine(root, QStringLiteral("libraries")),
                                   FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("libraries")) }) {
        if (QDir(candidate).exists()) {
            out.librariesDir = candidate;
            break;
        }
    }
    if (out.librariesDir.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "libraries: %1/libraries").arg(root);

    for (const auto& candidate : { FS::PathCombine(root, QStringLiteral("assets")),
                                   FS::PathCombine(root, QStringLiteral(".minecraft"), QStringLiteral("assets")) }) {
        if (QDir(candidate).exists()) {
            out.assetsDir = candidate;
            break;
        }
    }
    if (out.assetsDir.isEmpty())
        out.searched << QCoreApplication::translate("HorizonMinecraftFiles", "assets: %1/assets").arg(root);

    return out;
}

QStringList prepareArguments(const Located& files)
{
    QStringList args;
    if (files.versionJson.isEmpty() || files.clientJar.isEmpty() || files.librariesDir.isEmpty() || files.assetsDir.isEmpty())
        return args;

    // Horizon documents these four for "a launcher whose files aren't laid out like the official
    // launcher's, each names what --minecraft-dir would give".
    args << QStringLiteral("--version-json") << files.versionJson
         << QStringLiteral("--client-jar") << files.clientJar
         << QStringLiteral("--libraries-dir") << files.librariesDir
         << QStringLiteral("--assets-dir") << files.assetsDir;
    return args;
}

}  // namespace HorizonMinecraftFiles
