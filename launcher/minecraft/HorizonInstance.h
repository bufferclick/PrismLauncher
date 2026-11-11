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

#include "minecraft/MinecraftInstance.h"

class HorizonInstance;

/**
 * Launches a Horizon instance.
 *
 * Horizon is a native Rust program, so it is not started the way Minecraft is: there is no
 * JVM, no classpath and no launcher jar. The step simply runs the Horizon client with the
 * instance folder as its working directory, so Horizon reads the worlds and packs that live
 * there exactly as it would in its own install.
 */
class HorizonLaunchTask : public LaunchTask {
   public:
    static std::unique_ptr<HorizonLaunchTask> create(HorizonInstance* inst);

   protected:
    explicit HorizonLaunchTask(HorizonInstance* inst);
};

/**
 * A Horizon instance.
 *
 * It is a MinecraftInstance so it lives in the normal instance list, has an instance.cfg,
 * a mods folder, resource packs and an icon, and shows the usual pages. What differs is the
 * launch: HorizonLaunchTask runs the native client instead of java.
 *
 * Horizon's mods are `.hnmod` / `.hmod`, not Fabric jars, so the Java mod loader settings are
 * not meaningful here; the folders are still exposed so files can be dropped in.
 */
class HorizonInstance : public MinecraftInstance {
    Q_OBJECT

   public:
    HorizonInstance(SettingsObject* globalSettings, std::unique_ptr<SettingsObject> settings, const QString& rootDir);
    ~HorizonInstance() override = default;

    /// \brief The instance type string used in instance.cfg.
    static QString typeString() { return QStringLiteral("Horizon"); }

    LaunchTask* createLaunchTask(AuthSessionPtr account, MinecraftTarget::Ptr targetToJoin) override;

    /// \brief Path to the Horizon client this instance should run.
    QString horizonBinary() const;

    /// \brief Where Horizon keeps its data for this instance.
    QString horizonDataDir() const;

    /// \brief True when the configured/inferred client exists and is executable.
    bool isHorizonInstalled() const;

    /// \brief Windows only: the usual install locations, for the "find it for me" path.
    static QString findInstalledHorizon();
};
