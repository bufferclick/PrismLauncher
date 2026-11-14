// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonInstance.h"

#include <QJsonArray>
#include <QJsonObject>

#include "FileSystem.h"
#include "HorizonLaunchTask.h"
#include "HorizonPort.h"
#include "settings/SettingsObject.h"

HorizonInstance::HorizonInstance(SettingsObject* globalSettings, std::unique_ptr<SettingsObject> settings, const QString& rootDir)
    : MinecraftInstance(globalSettings, std::move(settings), rootDir)
{}

QString HorizonInstance::buildTag() const
{
    const QString tag = m_settings->get("HorizonBuild").toString();
    return tag.isEmpty() ? HorizonPort::buildTag() : tag;
}

// Horizon keeps its content mods in game/horizon-mods, not game/mods: that is
// the folder the engine reads (`docs/api/content.md`).
QString HorizonInstance::modsRoot() const
{
    return FS::PathCombine(gameRoot(), "horizon-mods");
}

QString HorizonInstance::instanceConfigFolder() const
{
    return FS::PathCombine(gameRoot(), "config");
}

QList<Task::Ptr> HorizonInstance::createUpdateTask()
{
    // Horizon does not update through Minecraft's version components. A new
    // build is fetched with `horizonport fetch` and prepared with
    // `horizonport prepare`; the instance keeps playing its pinned tag until
    // the player asks for the new one. Nothing to do here.
    return {};
}

LaunchTask* HorizonInstance::createLaunchTask(AuthSessionPtr account, MinecraftTarget::Ptr targetToJoin)
{
    Q_UNUSED(targetToJoin);
    return HorizonLaunchTask::create(this, std::move(account));
}

QString HorizonInstance::getStatusbarDescription()
{
    return tr("Horizon, build %1").arg(buildTag());
}

QStringList HorizonInstance::verboseDescription(AuthSessionPtr session, MinecraftTarget::Ptr targetToJoin)
{
    Q_UNUSED(session);
    Q_UNUSED(targetToJoin);

    QStringList lines;
    lines << tr("Build: %1").arg(buildTag());
    lines << tr("Game folder: %1").arg(gameRoot());
    lines << tr("Content mods are read from %1").arg(modsRoot());
    return lines;
}
