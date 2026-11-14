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

#include <QJsonObject>

#include "InstanceTask.h"

/**
 * Creates a Horizon instance and installs what it needs, in one go.
 *
 * This is the "add Horizon" action, and it is deliberately the whole first-run
 * experience: fetch the signed build, prepare its resources once, then create
 * the instance. The player never sees a folder dialog, never runs an installer,
 * and never has to find a file — which is exactly what the toolkit's own guide
 * asks for.
 *
 * Every step is a `horizonport` command; JL re-implements none of them. The
 * heavy work (a signed archive download, ~1 GiB of Minecraft files, minutes of
 * preparation) is why this is a Task with progress rather than a blocking call.
 */
class HorizonCreationTask final : public InstanceTask {
    Q_OBJECT

   public:
    explicit HorizonCreationTask(QString buildTag = {});

    void executeTask() override;
    bool abort() override;
    bool canAbort() const override;

   private:
    void createInstance();
    void fail(const QString& reason);

    QString m_buildTag;
    bool m_running = false;
};
