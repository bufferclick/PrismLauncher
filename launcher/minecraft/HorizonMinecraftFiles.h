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

#include <QString>
#include <QStringList>


class MinecraftInstance;

/**
 * Finds the Minecraft files JL already downloaded, so horizon-prepare can read them.
 *
 * Horizon warns that it "reads the official launcher's folder, ATLauncher's and the CurseForge
 * app's; for Prism Launcher, MultiMC, the Modrinth App or GDLauncher, prepare from the Horizon
 * launcher". JL has its own copy of the game, arranged Prism's way:
 *
 *   <dataRoot>/libraries/…            shared Maven libraries
 *   <dataRoot>/assets/indexes/…       asset indexes
 *   <dataRoot>/assets/objects/…       asset objects
 *   <dataRoot>/meta/*           the version JSON JL fetched
 *
 * None of that is the official layout, which is why Horizon reported "Missing
 * .minecraft/versions/26.3/26.3.json" for a version JL had already downloaded.
 *
 * Rather than copying gigabytes into a fake .minecraft, this reads the version JSON JL already
 * has and names each piece explicitly with --version-json, --client-jar, --libraries-dir and
 * --assets-dir, which Horizon documents for exactly this case.
 */
namespace HorizonMinecraftFiles {

struct Located {
    /// \brief True when enough was found for the preparer to run.
    ///
    /// The client jar is NOT required: Prism downloads the vanilla client through its meta cache
    /// and does not keep a <version>.jar beside the JSON, and horizon-prepare can take the jar
    /// from the version JSON's own downloads. Version JSON, libraries and assets are required.
    bool complete() const { return !versionJson.isEmpty() && !librariesDir.isEmpty() && !assetsDir.isEmpty(); }

    QString versionJson;
    QString clientJar;
    QString librariesDir;
    QString assetsDir;
    /// \brief The Minecraft version the files belong to, e.g. "26.3".
    QString version;
    /// \brief Human-readable account of what was searched, for the failure message.
    QStringList searched;
};

/// \brief Locate the Minecraft files for \a instance, which may be null.
///
/// Order: the instance's own version JSON when it has one, then JL's shared meta index. Every
/// candidate is checked for existence, so a stale path never wins.
Located locate(MinecraftInstance* instance, const QString& minecraftVersion);

/// \brief The arguments that name \a files to horizon-prepare, or empty when incomplete.
QStringList prepareArguments(const Located& files);

/// \brief One readable sentence about what a folder is missing, or empty when nothing is.
QString explain(const Located& files);

}  // namespace HorizonMinecraftFiles
