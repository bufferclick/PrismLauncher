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
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>

#include "Application.h"
#include "FileSystem.h"

namespace {
/// True when `parent` holds a runnable toolkit: the package in `parent/porting`,
/// importable as `porting.horizonport`.
///
/// Both halves matter. `python -m porting.horizonport` has to *import* `porting`
/// and then find `horizonport` inside it, so the folder that goes on PYTHONPATH
/// is the one holding `porting/`, and that folder must contain both __init__.py
/// files. Pointing PYTHONPATH at `porting/` itself cannot work: `porting` would
/// then have to be a module file, not a package, and Python reports
/// "No module named 'porting'" no matter how the process is started.
bool holdsToolkit(const QString& parent)
{
    return QFileInfo::exists(FS::PathCombine(parent, "porting", "__init__.py")) &&
           QFileInfo::exists(FS::PathCombine(parent, "porting", "horizonport", "__init__.py")) &&
           QFileInfo::exists(FS::PathCombine(parent, "porting", "horizonport", "__main__.py"));
}

// The toolkit is vendored at <repo>/porting/horizonport. A shipped build keeps
// it beside the executable, so both layouts are searched, in that order. The
// returned path is the folder that *contains* `porting/` — the import root.
QStringList candidateRoots()
{
    QStringList roots;
    if (auto configured = qEnvironmentVariable("HORIZONPORT"); !configured.isEmpty())
        roots << configured;
    roots << qApp->applicationDirPath();
    roots << FS::PathCombine(qApp->applicationDirPath(), "..");
    // A run straight from a build tree: climb out of build/ and look for the
    // source checkout's porting/ folder.
    QDir folder(qApp->applicationDirPath());
    for (int depth = 0; depth < 6; ++depth) {
        roots << folder.absolutePath();
        if (!folder.cdUp())
            break;
    }
    return roots;
}

/// Python's own wording for "the toolkit could not be imported". That message is
/// a packaging bug in JL, not something the player can act on, so it is
/// translated into what to do about it.
bool isImportFailure(const QString& message)
{
    return message.contains(QStringLiteral("No module named 'porting'")) ||
           message.contains(QStringLiteral("Error while finding module specification for 'porting.horizonport'"));
}

QString importFailureMessage(const QString& toolkit)
{
    return QObject::tr(
        "JL could not start the Horizon toolkit from %1. This is a fault in the installed copy of JL, not in your "
        "installation of Horizon; reinstalling JL fixes it. Set HORIZONPORT to the folder that contains porting/ to "
        "point JL at a different copy.")
        .arg(toolkit);
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
        if (holdsToolkit(root))
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
        if (reason) {
            QStringList looked = candidateRoots();
            for (auto& path : looked)
                path = QDir(path).absolutePath();
            looked.removeDuplicates();
            *reason = QObject::tr(
                          "The HorizonPort toolkit is missing. JL looked for porting/horizonport in: %1. "
                          "Reinstall JL, or set HORIZONPORT to the folder that contains porting/.")
                          .arg(looked.join(QStringLiteral(", ")));
        }
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

bool HorizonPort::parseError(QProcess& process, const QString& stdOut, QString* error)
{
    QString message = QString::fromUtf8(process.readAllStandardError()).trimmed();
    if (message.isEmpty())
        message = stdOut.trimmed();
    if (isImportFailure(message))
        message = importFailureMessage(toolkitRoot());
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
    QString pending;
    QElapsedTimer clock;
    clock.start();

    auto drainStdout = [&]() {
        const QString text = QString::fromUtf8(process.readAllStandardOutput());
        if (text.isEmpty())
            return;
        stdOut += text;
        // Emit complete lines only: a JSON event can be split across reads.
        pending += text;
        int newline = pending.indexOf('\n');
        while (newline >= 0) {
            const QString line = pending.left(newline).trimmed();
            pending.remove(0, newline + 1);
            if (!line.isEmpty() && onLine)
                onLine(line);
            newline = pending.indexOf('\n');
        }
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
        drainStdout();
        stdErr += QString::fromUtf8(process.readAllStandardError());
    }
    drainStdout();
    if (!pending.trimmed().isEmpty() && onLine)
        onLine(pending.trimmed());

    if (process.exitCode() != 0) {
        QString message = stdErr.trimmed();
        if (message.isEmpty())
            message = stdOut.trimmed();
        if (isImportFailure(message))
            message = importFailureMessage(toolkitRoot());
        if (error)
            *error = message.isEmpty() ? QObject::tr("horizonport exited with code %1").arg(process.exitCode()) : message;
        return false;
    }
    if (output) {
        for (const auto& line : stdOut.split('\n')) {
            const QString candidate = line.trimmed();
            if (!candidate.startsWith('{'))
                continue;
            const auto document = QJsonDocument::fromJson(candidate.toUtf8());
            if (document.isObject())
                *output = document.object();
        }
    }
    return true;
}
