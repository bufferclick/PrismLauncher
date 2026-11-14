// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonCreationTask.h"

#include <QDebug>
#include <QJsonArray>
#include <QJsonObject>

#include "FileSystem.h"
#include "HorizonInstance.h"
#include "HorizonPort.h"
#include "settings/INISettingsObject.h"

HorizonCreationTask::HorizonCreationTask(QString buildTag) : m_buildTag(std::move(buildTag))
{
    if (m_buildTag.isEmpty())
        m_buildTag = HorizonPort::buildTag();
}

bool HorizonCreationTask::canAbort() const
{
    // The build download and the preparation are both minutes long; a player
    // must be able to stop. Finished files are kept, so a retry resumes.
    return m_running;
}

bool HorizonCreationTask::abort()
{
    if (!canAbort())
        return false;
    emitAborted();
    return true;
}

void HorizonCreationTask::fail(const QString& reason)
{
    m_running = false;
    emitFailed(reason);
}

void HorizonCreationTask::executeTask()
{
    m_running = true;

    // ------------------------------------------------------------------
    // 0. The port project (created on first use, idempotent afterwards)
    // ------------------------------------------------------------------
    setStatus(tr("Preparing Horizon"));
    QString error;
    if (!HorizonPort::ensureProject(&error))
        return fail(error);

    // ------------------------------------------------------------------
    // 1. The signed build. On a later instance this is a no-op: the toolkit
    //    reports "already installed" and returns in milliseconds.
    // ------------------------------------------------------------------
    setStatus(tr("Installing Horizon %1 (a signed build, checked before use)").arg(m_buildTag));
    QJsonObject build;
    if (!HorizonPort::run({ "fetch", "--tag", m_buildTag }, &build, &error, 60 * 60 * 1000))
        return fail(error);

    // ------------------------------------------------------------------
    // 2. The resources, once per build and Minecraft version. This is the
    //    slow step: Mojang's files for the signed-in owner, then the engine's
    //    own exporters. A completed tree is reused forever.
    // ------------------------------------------------------------------
    setStatus(tr("Preparing Horizon's resources. First run only; this takes a few minutes."));
    QJsonObject prepared;
    const bool preparedOk = HorizonPort::runStreaming(
        { "prepare", "--build", m_buildTag },
        [this](const QString& line) {
            // The toolkit emits one JSON event per line: {message} or {fraction}.
            const auto document = QJsonDocument::fromJson(line.toUtf8());
            if (!document.isObject()) {
                setDetails(line);
                return;
            }
            const auto event = document.object();
            if (event.contains("message"))
                setDetails(event.value("message").toString());
            if (event.contains("fraction")) {
                const double fraction = event.value("fraction").toDouble();
                setProgress(static_cast<qint64>(fraction * 1000), 1000);
            }
        },
        &prepared, &error, 4 * 60 * 60 * 1000);
    if (!preparedOk)
        return fail(error);

    // ------------------------------------------------------------------
    // 3. The instance folder itself.
    // ------------------------------------------------------------------
    setStatus(tr("Creating the instance"));
    createInstance();
}

void HorizonCreationTask::createInstance()
{
    auto instanceSettings = std::make_unique<INISettingsObject>(FS::PathCombine(m_stagingPath, "instance.cfg"));

    // The instance type is what makes InstanceList load this back as a
    // HorizonInstance instead of a plain Minecraft one.
    instanceSettings->registerSetting("InstanceType", HorizonInstance::typeString());
    instanceSettings->set("InstanceType", HorizonInstance::typeString());
    instanceSettings->registerSetting("HorizonBuild", m_buildTag);
    instanceSettings->set("HorizonBuild", m_buildTag);
    instanceSettings->registerSetting("name", name());
    instanceSettings->set("name", name());
    instanceSettings->registerSetting("iconKey", m_instIcon);
    instanceSettings->set("iconKey", m_instIcon);

    m_running = false;
    emitSucceeded();
}
