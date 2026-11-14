// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#pragma once

#include "minecraft/MinecraftInstance.h"

/**
 * A Horizon instance.
 *
 * It is a MinecraftInstance so the folder layout, the pages and the settings
 * machinery keep working, but it launches the native Rust client instead of a
 * JVM: `createLaunchTask` returns a HorizonLaunchTask, which drives the
 * toolkit and then hands the session to `horizon-client` on stdin.
 *
 * There is no version JSON and no components: Horizon is a single client built
 * for one Minecraft version, and its resources are prepared once per build by
 * `horizonport prepare`.
 */
class HorizonInstance : public MinecraftInstance {
    Q_OBJECT

   public:
    HorizonInstance(SettingsObject* globalSettings, std::unique_ptr<SettingsObject> settings, const QString& rootDir);
    ~HorizonInstance() override = default;

    void saveNow() override {}
    void loadSpecificSettings() override {}

    QString modsRoot() const override;
    QString instanceConfigFolder() const override;

    /// The build tag recorded in instance.cfg, e.g. "nightly".
    QString buildTag() const;

    bool canEdit() const override { return false; }
    bool canExport() const override { return false; }

    /// No Minecraft component updates: Horizon updates by fetching a new build.
    QList<Task::Ptr> createUpdateTask() override;

    LaunchTask* createLaunchTask(AuthSessionPtr account, MinecraftTarget::Ptr targetToJoin) override;

    QString getStatusbarDescription() override;
    QStringList verboseDescription(AuthSessionPtr session, MinecraftTarget::Ptr targetToJoin) override;

    static QString typeString() { return QStringLiteral("Horizon"); }
};
