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

#include "HorizonPort.h"

#include <QApplication>
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>

#include "Application.h"
#include "FileSystem.h"

namespace {
// The toolkit is vendored at <repo>/porting/horizonport. A shipped build keeps
// it beside the executable, so both layouts are searched, in that order.
QStringList candidateRoots()
{
    QStringList roots;
    if (auto configured = qEnvironmentVariable("HORIZONPORT"); !configured.isEmpty())
        roots << configured;
    roots << FS::PathCombine(qApp->applicationDirPath(), "porting");
    roots << FS::PathCombine(qApp->applicationDirPath(), "..", "porting");
    roots << QStringLiteral(HORIZONPORT_SOURCE_ROOT) + "/porting";
    return roots;
}
}  // namespace

QString HorizonPort::projectDir()
{
    // Never inside the launcher's own installation: the store holds Mojang's
    // files and the secrets hold tokens. Both belong with the player's data.
    return FS::PathCombine(APPLICATION->dataRoot(), "horizonport");
}

QString HorizonPort::toolkitRoot()
{
    for (const auto& root : candidateRoots()) {
        if (QFileInfo::exists(FS::PathCombine(root, "horizonport", "__init__.py")))
            return QDir(root).absolutePath();
    }
    return {};
}

QString HorizonPort::pythonExecutable()
{
    if (auto configured = qEnvironmentVariable("HORIZONPORT_PYTHON"); !configured.isEmpty())
        return configured;
#ifdef Q_OS_WIN
    for (const auto& name : { "python.exe", "python3.exe" }) {
        if (auto found = QStandardPaths::findExecutable(name); !found.isEmpty())
            return found;
    }
    return QStringLiteral("python");
#else
    for (const auto& name : { "python3", "python" }) {
        if (auto found = QStandardPaths::findExecutable(name); !found.isEmpty())
            return found;
    }
    return QStringLiteral("python3");
#endif
}

bool HorizonPort::isAvailable(QString* reason)
{
    if (toolkitRoot().isEmpty()) {
        if (reason)
            *reason = QObject::tr("The HorizonPort toolkit is missing. Reinstall JL; the porting/ folder ships with it.");
        return false;
    }
    if (pythonExecutable().isEmpty()) {
        if (reason)
            *reason = QObject::tr("Python 3.11 or newer is required to run Horizon but was not found on PATH.");
        return false;
    }
    return true;
}

QStringList HorizonPort::baseArguments()
{
    return { "-m", "porting.horizonport", "--json", "--project", projectDir() };
}

bool HorizonPort::ensureProject(QString* error)
{
    if (!isAvailable(error))
        return false;

    const QString project = projectDir();
    if (QFileInfo::exists(FS::PathCombine(project, "port.config.json")))
        return true;

    if (!FS::ensureFolderPathExists(project)) {
        if (error)
            *error = QObject::tr("Could not create %1").arg(project);
        return false;
    }

    QProcess process;
    process.setWorkingDirectory(toolkitRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONPATH", toolkitRoot());
    process.setProcessEnvironment(env);
    process.start(pythonExecutable(),
                  { "-m", "porting.horizonport", "init", project, "--name", "JL", "--adapter", "none" });
    if (!process.waitForStarted(30000)) {
        if (error)
            *error = QObject::tr("Could not start Python: %1").arg(process.errorString());
        return false;
    }
    process.waitForFinished(120000);
    if (process.exitCode() != 0) {
        const QString stderrText = QString::fromUtf8(process.readAllStandardError()).trimmed();
        // "already exists" from a concurrent run is fine: the config is there.
        if (!QFileInfo::exists(FS::PathCombine(project, "port.config.json"))) {
            if (error)
                *error = stderrText.isEmpty() ? QObject::tr("horizonport init failed") : stderrText;
            return false;
        }
    }
    return true;
}

QString HorizonPort::buildTag()
{
    return qEnvironmentVariable("HORIZONPORT_BUILD_TAG", QStringLiteral("nightly"));
}

QString HorizonPort::stableTag()
{
    return qEnvironmentVariable("HORIZONPORT_STABLE_TAG", QString());
}

bool HorizonPort::parseError(const QProcess& process, const QString& stdOut, QString* error)
{
    QString message = QString::fromUtf8(process.readAllStandardError()).trimmed();
    if (message.isEmpty())
        message = stdOut.trimmed();
    if (message.isEmpty())
        message = QObject::tr("horizonport exited with code %1").arg(process.exitCode());
    if (error)
        *error = message;
    return false;
}

bool HorizonPort::run(const QStringList& arguments, QJsonObject* output, QString* error, int timeoutMs)
{
    if (!isAvailable(error))
        return false;

    QProcess process;
    process.setWorkingDirectory(toolkitRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONPATH", toolkitRoot());
    process.setProcessEnvironment(env);

    process.start(pythonExecutable(), baseArguments() + arguments);
    if (!process.waitForStarted(30000)) {
        if (error)
            *error = QObject::tr("Could not start Python: %1").arg(process.errorString());
        return false;
    }
    if (!process.waitForFinished(timeoutMs > 0 ? timeoutMs : 30 * 60 * 1000)) {
        process.kill();
        process.waitForFinished(5000);
        if (error)
            *error = QObject::tr("horizonport %1 timed out").arg(arguments.value(0));
        return false;
    }

    const QString stdOut = QString::fromUtf8(process.readAllStandardOutput());
    if (process.exitCode() != 0)
        return parseError(process, stdOut, error);

    if (output) {
        QJsonParseError parseError{};
        const auto document = QJsonDocument::fromJson(stdOut.toUtf8(), &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            if (error)
                *error = QObject::tr("horizonport %1 printed something that is not JSON")
                             .arg(arguments.value(0));
            return false;
        }
        *output = document.object();
    }
    return true;
}

bool HorizonPort::runStreaming(const QStringList& arguments,
                               const std::function<void(const QString&)>& onLine,
                               QJsonObject* output,
                               QString* error,
                               int timeoutMs)
{
    if (!isAvailable(error))
        return false;

    QProcess process;
    process.setWorkingDirectory(toolkitRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONPATH", toolkitRoot());
    // Without this the toolkit's console output is block-buffered when it is
    // not a terminal, and a minutes-long prepare would show nothing at all.
    env.insert("PYTHONUNBUFFERED", "1");
    process.setProcessEnvironment(env);

    process.start(pythonExecutable(), baseArguments() + arguments);
    if (!process.waitForStarted(30000)) {
        if (error)
            *error = QObject::tr("Could not start Python: %1").arg(process.errorString());
        return false;
    }

    QString stdOut;
    QString stdErr;
    QElapsedTimer clock;
    clock.start();
    auto consume = [&](bool final) {
        while (process.canReadLine()) {
            const QString line = QString::fromUtf8(process.readLine()).trimmed();
            if (!line.isEmpty() && onLine)
                onLine(line);
        }
        stdOut += QString::fromUtf8(process.readAllStandardOutput());
        stdErr += QString::fromUtf8(process.readAllStandardError());
    };

    while (process.state() != QProcess::NotRunning) {
        if (!process.waitForReadyRead(500)) {
            if (timeoutMs > 0 && clock.elapsed() > timeoutMs) {
                process.kill();
                process.waitForFinished(5000);
                if (error)
                    *error = QObject::tr("horizonport %1 timed out").arg(arguments.value(0));
                return false;
            }
            continue;
        }
        consume(false);
    }
    consume(true);

    if (process.exitCode() != 0) {
        QString message = stdErr.trimmed();
        if (message.isEmpty())
            message = stdOut.trimmed();
        if (error)
            *error = message.isEmpty() ? QObject::tr("horizonport exited with code %1").arg(process.exitCode()) : message;
        return false;
    }
    if (output) {
        const auto document = QJsonDocument::fromJson(stdOut.toUtf8());
        *output = document.object();
    }
    return true;
}
