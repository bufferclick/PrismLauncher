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

#include <memory>

#include "InstanceTask.h"
#include "minecraft/HorizonInstance.h"

/**
 * Creates a Horizon instance, and installs Horizon itself if it is not there yet.
 *
 * Creating an instance is the moment the user expects everything to be in place, so this
 * downloads Horizon's game files (the platform archive from its GitHub release) before the
 * instance is handed back. No folder is opened, no installer is run, and no separate trip to
 * Help → Horizon is needed.
 */
class HorizonCreationTask final : public InstanceTask {
    Q_OBJECT

   public:
    HorizonCreationTask() = default;

    /// \brief The one Minecraft version Horizon runs.
    ///
    /// Horizon is a native client built against a single game version, so an instance has no
    /// version to choose. Bump this when Horizon supports a newer game version.
    static QString gameVersion() { return QStringLiteral("26.3"); }

    void executeTask() override;

   private:
    void downloadHorizon();
    void finishCreation();

    std::unique_ptr<HorizonInstance> m_instance;
    bool m_createSucceeded = false;
};
