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
        m_instance->settings()->set("InstanceType", HorizonInstance::typeString());

        // Point at the installed client so the first launch works without extra setup.
        if (const auto binary = HorizonInstance::findInstalledHorizon(); !binary.isEmpty())
            m_instance->settings()->set("HorizonBinary", binary);
    }

    // The folders Horizon and its users expect, created up front.
    const auto root = m_instance->gameRoot();
    for (const auto& folder : { "mods", "resourcepacks", "saves", "screenshots" }) {
        if (!FS::ensureFolderPathExists(FS::PathCombine(root, folder))) {
            emitFailed(tr("Could not create %1").arg(folder));
            return;
        }
    }

    emitSucceeded();
}
