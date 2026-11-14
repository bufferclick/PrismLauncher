// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "DebugReport.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QProcess>
#include <QScreen>
#include <QStandardPaths>
#include <QSysInfo>
#include <QThread>

#include "Application.h"
#include "InstanceList.h"
#include "minecraft/auth/AccountList.h"
#include "BuildConfig.h"
#include "FileSystem.h"
#include "launch/LaunchTask.h"
#include "launch/LogModel.h"
#include "minecraft/MinecraftInstance.h"
#include "settings/SettingsObject.h"

namespace {

QString run(const QString& program, const QStringList& args, int timeoutMs = 4000)
{
    QProcess proc;
    proc.setProcessChannelMode(QProcess::MergedChannels);
    proc.start(program, args);
    if (!proc.waitForFinished(timeoutMs)) {
        proc.kill();
        return {};
    }
    return QString::fromLocal8Bit(proc.readAll()).trimmed();
}

QString humanBytes(qint64 bytes)
{
    constexpr qint64 kGiB = 1024LL * 1024 * 1024;
    constexpr qint64 kMiB = 1024LL * 1024;
    if (bytes >= kGiB)
        return QStringLiteral("%1 GiB").arg(QString::number(double(bytes) / kGiB, 'f', 1));
    return QStringLiteral("%1 MiB").arg(bytes / kMiB);
}

void section(QStringList& out, const QString& title)
{
    out << QString() << QStringLiteral("=== %1 ===").arg(title);
}

void row(QStringList& out, const QString& key, const QString& value)
{
    out << QStringLiteral("%1: %2").arg(key, value.isEmpty() ? QStringLiteral("(not available)") : value);
}

QString describeInstance(MinecraftInstance* inst)
{
    if (!inst)
        return QStringLiteral("(none)");
    const auto settings = inst->settings();
    return QStringLiteral("%1 [%2] min=%3 MiB max=%4 MiB type=%5")
        .arg(inst->name(), inst->id(), QString::number(settings->get("MinMemAlloc").toInt()),
             QString::number(settings->get("MaxMemAlloc").toInt()), inst->instanceType());
}

}  // namespace

QString DebugReport::suggestedFileName()
{
    return QStringLiteral("jl-debug-%1.txt").arg(QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd-HHmmss")));
}

QString DebugReport::collect()
{
    QStringList out;

    out << QStringLiteral("JL debug report");
    out << QStringLiteral("Generated %1").arg(QDateTime::currentDateTime().toString(Qt::ISODate));
    out << QStringLiteral("This report is local only. Nothing in it was uploaded.");

    // ---------------------------------------------------------------- version
    section(out, QStringLiteral("JL"));
    row(out, QStringLiteral("Version"), BuildConfig.printableVersionString());
    row(out, QStringLiteral("Build artifact"), BuildConfig.BUILD_ARTIFACT);
    row(out, QStringLiteral("Build platform"), BuildConfig.BUILD_PLATFORM);
    row(out, QStringLiteral("Updater repo"), BuildConfig.UPDATER_GITHUB_REPO);
    row(out, QStringLiteral("Data directory"), APPLICATION->dataRoot());
    row(out, QStringLiteral("Binary"), QCoreApplication::applicationFilePath());
    row(out, QStringLiteral("Portable"), QFileInfo::exists(FS::PathCombine(APPLICATION->dataRoot(), "portable.txt")) ? "yes" : "no");

    // ---------------------------------------------------------------- OS
    section(out, QStringLiteral("Operating system"));
    row(out, QStringLiteral("Product"), QSysInfo::prettyProductName());
    row(out, QStringLiteral("Kernel"), QSysInfo::kernelType() + QStringLiteral(" ") + QSysInfo::kernelVersion());
    row(out, QStringLiteral("CPU architecture"), QSysInfo::currentCpuArchitecture());
    row(out, QStringLiteral("CPU cores"), QString::number(QThread::idealThreadCount()));
    row(out, QStringLiteral("Qt version"), QString::fromLatin1(qVersion()));

    // ---------------------------------------------------------------- memory
    section(out, QStringLiteral("System memory"));
    if (QFile meminfo(QStringLiteral("/proc/meminfo")); meminfo.open(QIODevice::ReadOnly)) {
        const auto text = QString::fromLocal8Bit(meminfo.readAll());
        for (const auto& line : text.split('\n')) {
            if (line.startsWith(QStringLiteral("MemTotal:")) || line.startsWith(QStringLiteral("MemAvailable:")))
                out << line.trimmed();
        }
    } else {
#if defined(Q_OS_WIN)
        // wmic is deprecated; PowerShell is present on every Windows JL supports. wmic also
        // returns "TotalPhysicalMemory=NNN" with a trailing CR that broke the old parse.
        const auto raw = run(QStringLiteral("powershell"),
                             { "-NoProfile", "-Command",
                               "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory" },
                             8000);
        bool ok = false;
        const qint64 bytes = raw.trimmed().toLongLong(&ok);
        if (ok && bytes > 0) {
            row(out, QStringLiteral("Total physical"), humanBytes(bytes));
        } else {
            row(out, QStringLiteral("Total physical"), QStringLiteral("could not be read (%1)").arg(raw.left(80)));
        }
#else
        row(out, QStringLiteral("Total physical"), QString());
#endif
    }

    // ---------------------------------------------------------------- GPU
    section(out, QStringLiteral("GPU / display"));
    for (const auto* screen : QGuiApplication::screens()) {
        out << QStringLiteral("Screen %1: %2x%3 @ %4 DPI, dpr %5")
                   .arg(screen->name(), QString::number(screen->size().width()), QString::number(screen->size().height()),
                        QString::number(qRound(screen->logicalDotsPerInch())), QString::number(screen->devicePixelRatio(), 'f', 2));
    }
#if defined(Q_OS_WIN)
    {
        // Adapter descriptions, driver versions and VRAM. PowerShell returns one field per
        // line, which avoids guessing at wmic's CSV column order.
        const auto raw = run(QStringLiteral("powershell"),
                             { "-NoProfile", "-Command",
                               "Get-CimInstance Win32_VideoController | ForEach-Object { "
                               "\"$($_.Name)|$($_.DriverVersion)|$($_.AdapterRAM)\" }" },
                             8000);
        bool any = false;
        for (const auto& line : raw.split('\n')) {
            const auto trimmed = line.trimmed();
            if (trimmed.isEmpty())
                continue;
            const auto parts = trimmed.split('|');
            if (parts.size() < 3)
                continue;
            any = true;
            out << QStringLiteral("GPU: %1 | driver %2 | VRAM %3")
                       .arg(parts.at(0).trimmed(), parts.at(1).trimmed(), humanBytes(parts.at(2).trimmed().toLongLong()));
        }
        if (!any)
            out << QStringLiteral("(no adapter reported by Win32_VideoController)");
    }
#endif

    // ---------------------------------------------------------------- Java
    section(out, QStringLiteral("Java"));
    const auto javaPaths = {
        QStringLiteral("java"),
        QStringLiteral("javaw"),
    };
    for (const auto& candidate : javaPaths) {
        const auto path = QStandardPaths::findExecutable(candidate);
        if (path.isEmpty())
            continue;
        out << QStringLiteral("%1 -> %2").arg(candidate, path);
        const auto version = run(path, { "-version" });
        if (!version.isEmpty())
            out << QStringLiteral("  %1").arg(version.split('\n').first().trimmed());
    }
    row(out, QStringLiteral("JAVA_HOME"), qEnvironmentVariable("JAVA_HOME"));
    // The launcher bundles/downloads its own Java, which is what instances actually use.
    row(out, QStringLiteral("Launcher Java path"), APPLICATION->settings()->get("JavaPath").toString());

    // ---------------------------------------------------------------- accounts
    section(out, QStringLiteral("Accounts"));
    const auto accounts = APPLICATION->accounts();
    for (int i = 0; i < accounts->count(); ++i) {
        const auto account = accounts->at(i);
        // Never print tokens: only the type and display name.
        if (account)
            out << QStringLiteral("Account: %1 (%2)").arg(account->profileName(), account->typeString());
    }
    if (accounts->count() == 0)
        out << QStringLiteral("(no accounts configured)");

    // ---------------------------------------------------------------- instances
    section(out, QStringLiteral("Instances"));
    const auto list = APPLICATION->instances();
    for (int i = 0; i < list->count(); ++i) {
        out << QStringLiteral("- %1").arg(describeInstance(list->at(i)));
    }
    if (list->count() == 0)
        out << QStringLiteral("(no instances)");

    // ---------------------------------------------------------------- selected instance launch
    section(out, QStringLiteral("Last launch"));
    if (auto* inst = list->count() > 0 ? list->at(0) : nullptr) {
        auto task = inst->getLaunchTask();
        if (task) {
            row(out, QStringLiteral("Instance"), inst->name());
            row(out, QStringLiteral("Running"), inst->isRunning() ? "yes" : "no");
            row(out, QStringLiteral("Log model lines"), QString::number(task->getLogModel() ? task->getLogModel()->rowCount() : 0));
        } else {
            out << QStringLiteral("(no launch task recorded for %1)").arg(inst->name());
        }
    } else {
        out << QStringLiteral("(no instances to inspect)");
    }

    out << QString();
    out << QStringLiteral("End of report.");

    return out.join('\n');
}
