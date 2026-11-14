// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#pragma once

#include <QJsonObject>
#include <QProcess>
#include <QString>
#include <QStringList>

#include <functional>

/**
 * The bridge between JL and the HorizonPort toolkit.
 *
 * Every security-sensitive operation (signature checks, archive unpacking,
 * game-file downloads, resource preparation, launch-plan validation) is done
 * by `porting/horizonport`, which is vendored beside this source tree. JL
 * never re-implements any of it: a second downloader or a second signature
 * check would be a second set of bugs in the part where a bug means
 * "installed a tampered binary".
 *
 * The toolkit is driven exactly as its own guide documents: one process per
 * command, `--json` for machine-readable output, exit codes 0/1/2.
 */
class HorizonPort {
   public:
    /// The project folder: holds port.config.json, the store, instances, secrets.
    static QString projectDir();
    /// Where the toolkit lives (the folder containing `porting/horizonport`).
    static QString toolkitRoot();
    /// The Python interpreter used to run the toolkit.
    static QString pythonExecutable();

    /// True when the vendored toolkit is present and importable.
    static bool isAvailable(QString* reason = nullptr);

    /// Run one command and return its parsed `--json` object.
    /// Returns false and fills `error` on failure; `error` carries the
    /// toolkit's own message, which is written to be shown to the user.
    static bool run(const QStringList& arguments, QJsonObject* output, QString* error, int timeoutMs = 0);

    /// Run one command, streaming its stdout lines to `onLine`.
    /// Used for long operations (prepare) where the caller wants progress.
    static bool runStreaming(const QStringList& arguments,
                             const std::function<void(const QString&)>& onLine,
                             QJsonObject* output,
                             QString* error,
                             int timeoutMs = 0);

    /// Create the port project if it does not exist yet. Idempotent.
    static bool ensureProject(QString* error);

    /// The Horizon build tag this launcher installs (the nightly channel).
    static QString buildTag();
    /// The stable channel tag, when the player wants a fixed release.
    static QString stableTag();

   private:
    static QStringList baseArguments();
    static bool parseError(QProcess& process, const QString& stdOut, QString* error);
};
