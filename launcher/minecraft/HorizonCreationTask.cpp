// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonCreationTask.h"

#include <QDir>

#include "FileSystem.h"
#include "minecraft/HorizonBuilds.h"
#include "minecraft/HorizonResources.h"
#include "minecraft/PackProfile.h"
#include "settings/INISettingsObject.h"
#include "settings/SettingsObject.h"

void HorizonCreationTask::executeTask()
{
    setStatus(tr("Creating Horizon instance"));

    m_instance = std::make_unique<HorizonInstance>(
        m_globalSettings, std::make_unique<INISettingsObject>(FS::PathCombine(m_stagingPath, "instance.cfg")), m_stagingPath);

    {
        const SettingsObject::Lock lock(m_instance->settings());

        // No components: Horizon is not assembled from Minecraft libraries. Saved so the
        // instance loads cleanly next time.
        auto* components = m_instance->getPackProfile();
        components->buildingFromScratch();
        components->saveNow();

        m_instance->setName(name());
        m_instance->setIconKey(m_instIcon.isEmpty() ? QStringLiteral("default") : m_instIcon);

        // settings() runs loadSpecificSettings(), which (in MinecraftInstance) writes
        // InstanceType=OneSix. Setting the type after that call, inside the Lock, means the
        // value written when the Lock is released is the Horizon one.
        m_instance->settings()->set("InstanceType", HorizonInstance::typeString());

        // Run whichever build JL has unpacked. Empty means "newest installed", which is what a
        // fresh instance wants: the download below fills it in.
        m_instance->settings()->set("HorizonBuildTag", HorizonBuilds::newestInstalledTag());
        m_instance->settings()->set("HorizonResources", HorizonResources::newestPrepared());

        // Remembered so the instance can say which game version it belongs to without asking.
        m_instance->settings()->set("HorizonGameVersion", gameVersion());
    }

    // The folders Horizon and its users expect, created up front.
    const auto root = m_instance->gameRoot();
    for (const auto& folder : { "mods", "resourcepacks", "saves", "screenshots" }) {
        if (!FS::ensureFolderPathExists(FS::PathCombine(root, folder))) {
            emitFailed(tr("Could not create %1").arg(folder));
            return;
        }
    }

    // Everything the instance needs on disk exists; now make sure Horizon itself does too, so
    // the first Launch works instead of sending the user off to install something.
    m_createSucceeded = true;
    downloadHorizon();
}

void HorizonCreationTask::downloadHorizon()
{
    if (HorizonBuilds::isComplete(HorizonBuilds::buildDir(HorizonBuilds::newestInstalledTag()))) {
        // Already installed and current enough; the launch step updates it if there is a newer one.
        setStatus(tr("Horizon is already installed"));
        finishCreation();
        return;
    }

    setStatus(tr("Downloading Horizon"));
    auto* task = new HorizonDownloadTask(QString(), nullptr);
    connect(task, &HorizonDownloadTask::logLine, this, [this](const QString& line) { logWarning(line); });
    connect(task, &Task::succeeded, this, [this, task] {
        const auto tag = task->installedTag();
        task->deleteLater();
        setStatus(tr("Horizon %1 downloaded").arg(tag));

        const SettingsObject::Lock lock(m_instance->settings());
        m_instance->settings()->set("HorizonBuildTag", tag);
        // A fresh build has no prepared resources until horizon-prepare has run; leave the field
        // empty rather than pointing at another build's folder.
        m_instance->settings()->set("HorizonResources", HorizonResources::newestPrepared());
        finishCreation();
    });
    connect(task, &Task::failed, this, [this, task](const QString& reason) {
        task->deleteLater();
        // The instance itself is usable and Horizon can be fetched later from Help → Horizon; a
        // failed download must not throw away the instance the user just asked for.
        logWarning(tr("Horizon could not be downloaded: %1").arg(reason));
        finishCreation();
    });
    task->start();
}

void HorizonCreationTask::finishCreation()
{
    if (m_createSucceeded) {
        emitSucceeded();
    }
}
