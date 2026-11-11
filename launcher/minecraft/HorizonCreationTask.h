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
 * Creates a Horizon instance.
 *
 * Unlike VanillaCreationTask this downloads nothing: Horizon is a separate program that the
 * user installs (Help → Horizon) and that reads its own prepared game data. The instance only
 * needs an instance.cfg, a folder layout and a pointer at the client.
 */
class HorizonCreationTask final : public InstanceTask {
    Q_OBJECT

   public:
    HorizonCreationTask() = default;

    void executeTask() override;

   private:
    std::unique_ptr<HorizonInstance> m_instance;
};
