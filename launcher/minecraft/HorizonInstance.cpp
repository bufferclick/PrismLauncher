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
#include "LoggedProcess.h"
#include "launch/LaunchStep.h"
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
            const QString reason = tr("Horizon is not installed. Install it from Help → Horizon, "
                                     "or set the client path in this instance's settings.");
            emit logLine(reason, MessageLevel::Fatal);
            emitFailed(reason);
            return;
        }

        auto* instanceSettings = m_instance->settings();
        const auto dataDir = m_instance->horizonDataDir();
        if (!FS::ensureFolderPathExists(dataDir)) {
            const QString reason = tr("Could not create the Horizon data folder: %1").arg(dataDir);
            emit logLine(reason, MessageLevel::Fatal);
            emitFailed(reason);
            return;
        }

        emit logLine(tr("Starting Horizon: %1").arg(binary), MessageLevel::Launcher);
        emit logLine(tr("Data folder: %1").arg(dataDir), MessageLevel::Launcher);

        m_process.setDetachable(true);
        m_process.setProcessEnvironment(m_instance->createLaunchEnvironment());
        m_process.setWorkingDirectory(dataDir);

        // Horizon accepts extra arguments; split the stored string the way a shell would.
        const auto args = QProcess::splitCommand(instanceSettings->get("HorizonArgs").toString());
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
                const QString reason = tr("Could not start Horizon: %1").arg(m_process.errorString());
                emit logLine(reason, MessageLevel::Fatal);
                emitFailed(reason);
                return;
            }
            case LoggedProcess::Aborted:
            case LoggedProcess::Crashed: {
                m_parent->setPid(-1);
                m_parent->instance()->setMinecraftRunning(false);
                emitFailed(tr("Horizon crashed or was closed by the launcher."));
                return;
            }
            case LoggedProcess::Finished: {
                const int exitCode = m_process.exitCode();
                m_parent->setPid(-1);
                m_parent->instance()->setMinecraftRunning(false);
                emit logLine(tr("Horizon exited with code %1.").arg(exitCode), MessageLevel::Launcher);
                // Same rule as a Java instance: a non-zero exit is a crash, not a quiet quit.
                if (exitCode != 0) {
                    emitFailed(tr("Horizon crashed (exit code %1).").arg(exitCode));
                    return;
                }
                emitSucceeded();
                return;
            }
            case LoggedProcess::Running:
                emit logLine(tr("Horizon process ID: %1").arg(m_process.processId()), MessageLevel::Launcher);
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
    // LaunchTask::create() is what normally calls init(); HorizonLaunchTask is constructed
    // directly here (its ctor is protected), so init() has to be called by hand. Without it the
    // instance is never marked as running and the UI stays on "Launch".
    task->init();
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
    if (!m_settings->getSetting("InstanceType"))
        m_settings->registerSetting("InstanceType", QString());
    m_settings->set("InstanceType", typeString());

    m_settings->registerSetting("HorizonBinary", QString());
    m_settings->registerSetting("HorizonArgs", QString());
}

void HorizonInstance::loadSpecificSettings()
{
    MinecraftInstance::loadSpecificSettings();
    // MinecraftInstance force-writes "OneSix" here (it cannot know about subclasses), so put the
    // real type back. Without this the instance would silently become a Java instance after the
    // first launch and stop using HorizonLaunchTask.
    if (m_settings->get("InstanceType").toString() != typeString())
        m_settings->set("InstanceType", typeString());
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
