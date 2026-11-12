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

#include <QDateTime>
#include <QDir>
#include <QMessageBox>
#include <QFileInfo>
#include <QLocale>
#include <QStandardPaths>

#include "Application.h"
#include "FileSystem.h"
#include "minecraft/HorizonBuilds.h"
#include "minecraft/auth/AccountList.h"
#include "minecraft/auth/AuthSession.h"
#include "minecraft/auth/MinecraftAccount.h"
#include "minecraft/HorizonResources.h"
#include "MMCTime.h"
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
        const auto buildDir = m_instance->horizonBuildDir();
        const auto client = HorizonBuilds::clientPath(buildDir);
        if (client.isEmpty()) {
            const QString reason =
                tr("No Horizon build is installed. JL downloads one from Help → Horizon, or press "
                   "Update on the instance to fetch the newest nightly.");
            emit logLine(reason, MessageLevel::Fatal);
            QMessageBox::warning(nullptr, tr("No Horizon build"), reason);
            emitFailed(reason);
            return;
        }

        const auto resources = m_instance->horizonResourcesDir();
        if (resources.isEmpty()) {
            const QString reason =
                tr("Horizon's game resources have not been prepared for this build yet.\n\n"
                   "Use Help → Horizon → Prepare, which turns your own copy of Minecraft into the "
                   "files Horizon reads.");
            emit logLine(reason, MessageLevel::Fatal);
            QMessageBox::warning(nullptr, tr("Horizon is not prepared"), reason);
            emitFailed(reason);
            return;
        }

        const auto gameDir = m_instance->horizonDataDir();
        if (!FS::ensureFolderPathExists(gameDir)) {
            const QString reason = tr("Could not create the Horizon game folder: %1").arg(gameDir);
            emit logLine(reason, MessageLevel::Fatal);
            emitFailed(reason);
            return;
        }

        // Per Horizon's Launch API: one folder per instance, the account's session on stdin,
        // never a token on the command line.
        QStringList args{ "--resources", resources, "--game-dir", gameDir, "--home", gameDir };

        // Only options the build lists are accepted (anything else exits 2), so the window size
        // and fullscreen flags are passed only when the instance actually sets them.
        if (auto geometry = m_instance->settings()->get("HorizonGeometry").toString(); !geometry.isEmpty())
            args << QProcess::splitCommand(geometry);

        const auto session = m_instance->horizonSessionJson();
        if (session.isEmpty()) {
            emit logLine(tr("No Microsoft account is available; Horizon will start signed out."), MessageLevel::Warning);
        } else {
            args << "--session-stdin";
        }

        emit logLine(tr("Horizon build: %1").arg(buildDir), MessageLevel::Launcher);
        emit logLine(tr("Resources: %1").arg(resources), MessageLevel::Launcher);
        emit logLine(tr("Game folder: %1").arg(gameDir), MessageLevel::Launcher);

        m_process.setDetachable(true);
        m_process.setProcessEnvironment(m_instance->createLaunchEnvironment());
        // Run from the folder holding the programs: the archive nests them one level down, and
        // horizon-prepare looks for research-lock.json and exporters/ beside itself.
        m_process.setWorkingDirectory(HorizonBuilds::rootOf(buildDir));
        m_process.start(client, args);

        if (!session.isEmpty() && m_process.waitForStarted(5000)) {
            // Write and close: the game reads the session once.
            m_process.write(session.toUtf8());
            m_process.closeWriteChannel();
        }
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
                // Horizon's documented exit codes: 0 quit, 1 stopped on an error, 2 refused
                // command line, 101 panicked.
                switch (exitCode) {
                    case 0:
                        emitSucceeded();
                        return;
                    case 2:
                        emitFailed(tr("Horizon refused the command line. This is a bug in JL; the "
                                      "console above names the option."));
                        return;
                    case 101:
                        emitFailed(tr("Horizon panicked. Its crash report path is on the last line "
                                      "of the console above."));
                        return;
                    default:
                        emitFailed(tr("Horizon stopped on an error (exit code %1). Its crash report "
                                      "path is in the console above.")
                                       .arg(exitCode));
                        return;
                }
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
// Launch step: keep the build current, then run it.
// ---------------------------------------------------------------------------------------

class HorizonUpdateStep : public LaunchStep {
    Q_OBJECT

   public:
    HorizonUpdateStep(LaunchTask* parent, HorizonInstance* instance) : LaunchStep(parent), m_instance(instance) {}

    void executeTask() override
    {
        if (!m_instance->settings()->get("HorizonAutoUpdate").toBool()) {
            emitSucceeded();
            return;
        }

        const auto current = QFileInfo(m_instance->horizonBuildDir()).fileName();
        auto* task = new HorizonUpdateTask(current, nullptr);
        connect(task, &HorizonUpdateTask::logLine, this,
                [this](const QString& line) { emit logLine(line, MessageLevel::Launcher); });
        connect(task, &Task::succeeded, this, [this, task] {
            if (task->updated()) {
                // Point the instance at what was just installed, oldest build left on disk.
                m_instance->settings()->set("HorizonBuildTag", task->installedTag());
                emit logLine(tr("Horizon updated to %1.").arg(task->installedTag()), MessageLevel::Launcher);
            }
            task->deleteLater();
            emitSucceeded();
        });
        connect(task, &Task::failed, this, [this, task](const QString& reason) {
            task->deleteLater();
            // Never block a launch because a check failed; the installed build is still there.
            emit logLine(tr("Horizon update skipped: %1").arg(reason), MessageLevel::Warning);
            emitSucceeded();
        });
        task->start();
    }

    bool abort() override { return true; }

   private:
    HorizonInstance* m_instance;
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
    // Update first, then run: Horizon publishes several builds a day, and the user asked for the
    // newest one on every start. The step never fails the launch.
    task->appendStep(shared_qobject_ptr<LaunchStep>(new HorizonUpdateStep(task.get(), inst)));
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

    m_settings->registerSetting("HorizonBuildTag", QString());
    m_settings->registerSetting("HorizonResources", QString());
    m_settings->registerSetting("HorizonGeometry", QString());
    m_settings->registerSetting("HorizonArgs", QString());
    m_settings->registerSetting("HorizonGameVersion", QString());
    // Checked on every launch; the build is replaced when GitHub has a newer one.
    m_settings->registerSetting("HorizonAutoUpdate", true);
    m_settings->registerSetting("HorizonLastChecked", QString());
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

QString HorizonInstance::horizonGameVersion() const
{
    return m_settings->get("HorizonGameVersion").toString();
}

QString HorizonInstance::horizonLauncher() const
{
    // Native mods are compiled into the game by horizon-launcher, which is a SEPARATE download
    // from the game files. Per Horizon's own guide, the game archive (horizon-windows-x64.zip)
    // only contains horizon-client, horizon-prepare, research-lock.json and exporters/.
    // If the user got horizon-launcher from playhorizon.dev it may sit next to the client, on
    // PATH, or in JL's own horizon folder.
    const auto client = HorizonBuilds::clientPath(horizonBuildDir());
    if (!client.isEmpty()) {
        const QFileInfo info(client);  // already inside the real root
        for (const auto& name : { "horizon-launcher.exe", "horizon-launcher" }) {
            const auto sibling = FS::PathCombine(info.absolutePath(), name);
            if (QFileInfo::exists(sibling))
                return sibling;
        }
    }
    for (const auto& name : { "horizon-launcher.exe", "horizon-launcher" }) {
        const auto candidate = FS::PathCombine(HorizonBuilds::buildsRoot(), name);
        if (QFileInfo::exists(candidate))
            return candidate;
    }
    return QStandardPaths::findExecutable(QStringLiteral("horizon-launcher"));
}

QString HorizonInstance::getStatusbarDescription()
{
    // Horizon instances have no components, so the base implementation would print
    // "Minecraft " and stop. Name the client and the game version instead.
    const auto version = horizonGameVersion();
    QString description = version.isEmpty() ? tr("Horizon") : tr("Horizon (Minecraft %1)").arg(version);

    if (m_settings->get("ShowGameTime").toBool()) {
        if (lastTimePlayed() > 0 && lastLaunch() > 0) {
            const auto lastLaunchTime = QDateTime::fromMSecsSinceEpoch(lastLaunch());
            description.append(
                tr(", last played on %1 for %2")
                    .arg(QLocale().toString(lastLaunchTime, QLocale::ShortFormat))
                    .arg(Time::prettifyDuration(lastTimePlayed(),
                                                APPLICATION->settings()->get("ShowGameTimeWithoutDays").toBool())));
        }
        if (totalTimePlayed() > 0) {
            description.append(
                tr(", total played for %1")
                    .arg(Time::prettifyDuration(totalTimePlayed(), APPLICATION->settings()->get("ShowGameTimeWithoutDays").toBool())));
        }
    }
    if (hasCrashed()) {
        description.append(tr(", has crashed."));
    }
    return description;
}

QString HorizonInstance::horizonBuildDir() const
{
    // Explicitly pinned build, else the newest one JL has unpacked.
    if (const auto pinned = m_settings->get("HorizonBuildTag").toString(); !pinned.isEmpty()) {
        const auto dir = HorizonBuilds::buildDir(pinned);
        if (HorizonBuilds::isComplete(dir))
            return dir;
    }
    return HorizonBuilds::buildDir(HorizonBuilds::newestInstalledTag());
}

QString HorizonInstance::horizonResourcesDir() const
{
    const auto dir = m_settings->get("HorizonResources").toString();
    if (dir.isEmpty())
        return {};
    // Horizon's own "--check" is what decides whether resources are usable; a folder that is
    // merely present may be half-prepared, so only trust one the check passed for.
    if (QFileInfo::exists(FS::PathCombine(dir, QStringLiteral("research-lock.json"))))
        return dir;
    return {};
}

QString HorizonInstance::horizonSessionJson() const
{
    // Horizon wants the owner's own Microsoft session: name, uuid, access_token, user_type.
    auto* accounts = APPLICATION->accounts();
    if (!accounts || !accounts->defaultAccount())
        return {};
    const auto account = accounts->defaultAccount();
    if (!account->ownsMinecraft())
        return {};

    const auto session = std::make_shared<AuthSession>();
    account->fillSession(session);
    if (session->access_token.isEmpty())
        return {};

    // uuid without dashes, as the Launch API example shows.
    const auto uuid = QString(session->uuid).remove('-');
    return QStringLiteral(R"({"name":"%1","uuid":"%2","access_token":"%3","user_type":"msa"})")
        .arg(session->player_name, uuid, session->access_token);
}

bool HorizonInstance::isHorizonReady() const
{
    return !HorizonBuilds::clientPath(horizonBuildDir()).isEmpty() && !horizonResourcesDir().isEmpty();
}

LaunchTask* HorizonInstance::createLaunchTask(AuthSessionPtr, MinecraftTarget::Ptr)
{
    // No account arguments: Horizon signs in itself with the user's own Microsoft account.
    return HorizonLaunchTask::create(this).release();
}

#include "HorizonInstance.moc"
