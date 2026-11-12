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

/**
 * Horizon's builds: where they come from, where they live, and how JL keeps them current.
 *
 * Per Horizon's own "Running Horizon from another launcher"
 * (docs/api/launch-guide.md), a build is a GitHub release of horizon-rust/horizon containing
 * ONE archive per platform. `horizon-windows-x64.zip` is **the game files a launcher installs**
 * — horizon-client, horizon-prepare, research-lock.json and exporters/ — not a launcher and not
 * an installer. Unpacking it into a folder of its own is the whole install.
 *
 * The newest build is the release tagged `nightly`; dated `nightly-<date>` tags are deleted after
 * seven days, so they are never pinned. Stable tags like `v0.2.97` are kept.
 */
namespace HorizonBuilds {

/// The GitHub API endpoint that lists builds, newest first.
constexpr auto kReleasesApi = "https://api.github.com/repos/horizon-rust/horizon/releases";

/// The release tag whose assets are the newest build.
constexpr auto kNightlyTag = "nightly";

/// \brief The archive name for this platform, or empty when Horizon has no build for it.
QString platformAsset();

/// \brief Root of every installed build: <dataRoot>/horizon.
QString buildsRoot();

/// \brief The folder one tag is unpacked into: <dataRoot>/horizon/<tag>.
QString buildDir(const QString& tag);

/// \brief The folder that actually holds the programs.
///
/// The archive packs everything inside one top-level folder named after the archive
/// (`7z a -tzip horizon-windows-x64.zip horizon-windows-x64`), so the real root is one level
/// below the unpack folder. Both layouts are handled.
QString rootOf(const QString& dir);

/// \brief The client binary inside an unpacked build, or empty if it is not there.
QString clientPath(const QString& buildDir);

/// \brief The preparer binary inside an unpacked build, or empty if it is not there.
QString preparePath(const QString& buildDir);

/// \brief True when this folder holds a usable build (client and preparer present).
bool isComplete(const QString& buildDir);

/// \brief The tag JL should run: the newest build that is fully unpacked.
QString newestInstalledTag();

}  // namespace HorizonBuilds
