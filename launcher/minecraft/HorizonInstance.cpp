// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonInstance.h"

#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

#include "FileSystem.h"
#include "launch/LaunchTask.h"
#include "launch/LoggedProcess.h"
#include "settings/SettingsObject.h"

// ---------------------------------------------------------------------------------------
// Launch step: run the native client.
// ---------------------------------------------------------------------------------------

class HorizonLaunchStep : public LaunchStep {
    Q_OBJECT

   public:
    explicit HorizonLaunchStep(LaunchTask* parent, HorizonInstance* instance)
        : LaunchStep(parent), m_instance(instance)
    {
        connect(&m_process, &LoggedProcess::log, this, &HorizonLaunchStep::logLines);
        connect(&m_process, &LoggedProcess::stateChanged, this, &HorizonLaunchStep::on_state);
    }

    void executeTask() override
    {
        const auto binary = m_instance->horizonBinary();
        if (binary.isEmpty() || !QFileInfo::exists(binary)) {
            const char* reason = QT_TR_NOOP("Horizon is not installed. Install it from Help → Horizon, "
                                            "or set the client path in this instance's settings.");
            emit logLine(tr(reason), MessageLevel::Fatal);
            emitFailed(tr(reason));
            return;
        }

        auto* instanceSettings = m_instance->settings();
        const auto dataDir = m_instance->horizonDataDir();
        if (!FS::ensureFolderPathExists(dataDir)) {
            const char* reason = QT_TR_NOOP("Could not create the Horizon data folder: %1");
            emit logLine(QString(reason).arg(dataDir), MessageLevel::Fatal);
            emitFailed(QString(reason).arg(dataDir));
            return;
        }

        emit logLine(tr("Starting Horizon: %1").arg(binary), MessageLevel::Launcher);
        emit logLine(tr("Data folder: %1").arg(dataDir), MessageLevel::Launcher);

        m_process.setDetachable(true);
        m_process.setProcessEnvironment(m_instance->createLaunchEnvironment());
        m_process.setWorkingDirectory(dataDir);

        // Horizon accepts a game directory; pass it explicitly so a moved install still works.
        QStringList args{ instanceSettings->get("HorizonArgs").toString() };
        m_process.start(binary, args);
    }

    bool abort() override
    {
        m_process.kill();
        return true;
    }

   private slots:
    void on_state(LoggedProcess::State state)
    {
        switch (state) {
            case LoggedProcess::FailedToStart: {
                const char* reason = QT_TR_NOOP("Could not start Horizon: %1");
                emit logLine(QString(reason).arg(m_process.errorString()), MessageLevel::Fatal);
                emitFailed(QString(reason).arg(m_process.errorString()));
                return;
            }
            case LoggedProcess::Aborted:
            case LoggedProcess::Crashed:
                m_parent->instance()->setMinecraftRunning(false);
                emitFailed(tr("Horizon exited."));
                return;
            case LoggedProcess::Finished: {
                m_parent->instance()->setMinecraftRunning(false);
                // Horizon closing normally is not a launcher failure; report the exit code.
                emit logLine(tr("Horizon exited with code %1.").arg(m_process.exitCode()), MessageLevel::Launcher);
                emitSucceeded();
                return;
            }
            case LoggedProcess::Running:
                m_parent->setPid(m_process.processId());
                m_parent->instance()->setMinecraftRunning(true);
                return;
            default:
                return;
        }
    }

   private:
    HorizonInstance* m_instance;
    LoggedProcess m_process;
};

// ---------------------------------------------------------------------------------------
// Launch task
// ---------------------------------------------------------------------------------------

HorizonLaunchTask::HorizonLaunchTask(HorizonInstance* inst) : LaunchTask(inst) {}

std::unique_ptr<HorizonLaunchTask> HorizonLaunchTask::create(HorizonInstance* inst)
{
    std::unique_ptr<HorizonLaunchTask> task(new HorizonLaunchTask(inst));
    task->appendStep(shared_qobject_ptr<LaunchStep>(new HorizonLaunchStep(task.get(), inst)));
    return task;
}

// ---------------------------------------------------------------------------------------
// Instance
// ---------------------------------------------------------------------------------------

HorizonInstance::HorizonInstance(SettingsObject* globalSettings, std::unique_ptr<SettingsObject> settings, const QString& rootDir)
    : MinecraftInstance(globalSettings, std::move(settings), rootDir)
{
    // Horizon instances are not Java instances; make it possible to tell them apart without
    // touching the components file.
    if (auto type = m_settings->get("InstanceType").toString(); type != typeString())
        m_settings->set("InstanceType", typeString());

    m_settings->registerSetting("HorizonBinary", "");
    m_settings->registerSetting("HorizonArgs", "");
}

QString HorizonInstance::horizonDataDir() const
{
    return gameRoot();
}

QString HorizonInstance::horizonBinary() const
{
    const auto configured = m_settings->get("HorizonBinary").toString();
    if (!configured.isEmpty())
        return configured;

    // A binary dropped into the instance folder wins, then whatever the install dialog found.
    for (const auto& candidate : { "horizon.exe", "Horizon.exe", "horizon-launcher.exe", "horizon" }) {
        const auto path = FS::PathCombine(instanceRoot(), candidate);
        if (QFileInfo::exists(path))
            return path;
    }

    return findInstalledHorizon();
}

bool HorizonInstance::isHorizonInstalled() const
{
    const auto binary = horizonBinary();
    return !binary.isEmpty() && QFileInfo::exists(binary);
}

QString HorizonInstance::findInstalledHorizon()
{
#if defined(Q_OS_WIN)
    // The Horizon launcher installs per-user; these are the locations its installer uses.
    const QStringList roots = { qEnvironmentVariable("LOCALAPPDATA"), qEnvironmentVariable("PROGRAMFILES"),
                                qEnvironmentVariable("PROGRAMFILES(X86)"), qEnvironmentVariable("APPDATA") };
    const QStringList names = { "Horizon", "horizon", "Horizon Launcher", "horizon-launcher" };
    const QStringList exes = { "horizon.exe", "Horizon.exe", "horizon-launcher.exe" };

    for (const auto& root : roots) {
        if (root.isEmpty())
            continue;
        for (const auto& name : names) {
            const QDir base(FS::PathCombine(root, name));
            if (!base.exists())
                continue;
            for (const auto& exe : exes) {
                const auto direct = base.absoluteFilePath(exe);
                if (QFileInfo::exists(direct))
                    return direct;
            }
            // One level of nesting is common ("Horizon/app/horizon.exe").
            for (const auto& sub : base.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
                for (const auto& exe : exes) {
                    const auto nested = base.absoluteFilePath(sub + "/" + exe);
                    if (QFileInfo::exists(nested))
                        return nested;
                }
            }
        }
    }
#endif
    // Fall back to PATH.
    for (const auto& exe : { "horizon", "horizon-launcher" }) {
        const auto found = QStandardPaths::findExecutable(exe);
        if (!found.isEmpty())
            return found;
    }
    return {};
}

LaunchTask* HorizonInstance::createLaunchTask(AuthSessionPtr, MinecraftTarget::Ptr)
{
    // No account arguments: Horizon signs in itself with the user's own Microsoft account.
    return HorizonLaunchTask::create(this).release();
}

#include "HorizonInstance.moc"
