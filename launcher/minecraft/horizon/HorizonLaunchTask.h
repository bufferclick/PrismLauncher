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
#include <QStringList>

#include "launch/LaunchTask.h"
#include "minecraft/auth/AuthSession.h"

class HorizonInstance;

/**
 * Starts Horizon, the way its Launch API (0.1.x) defines it.
 *
 * The sequence is the one `porting/launch.md` documents, and none of it is
 * guessed:
 *
 *   1. `horizonport play NAME --dry-run` returns the exact argv, validated
 *      against the build's own `--launch-api` reply. An option the build does
 *      not list can never reach it, because the toolkit refuses to build it.
 *   2. The session JSON is written to the child's stdin and stdin is closed,
 *      so the access token is never on a command line, in argv, in the
 *      environment or in a file on disk.
 *   3. The exit code is reported as the Launch API defines it: 0 quit,
 *      1 error, 2 a bug in this launcher, 101 panic. On 1/101 the crash
 *      report path is the last line on stderr and is shown to the player.
 */
class HorizonLaunchTask : public LaunchTask {
    Q_OBJECT

   public:
    static HorizonLaunchTask* create(HorizonInstance* instance, AuthSessionPtr session);

    void executeTask() override;
    bool abort() override;
    bool canAbort() const override;

   protected:
    HorizonLaunchTask(HorizonInstance* instance, AuthSessionPtr session);

   private:
    HorizonInstance* horizonInstance() const;
    QStringList planArguments() const;
    void startGame(const QJsonObject& plan);
    void reportExit(int code, const QString& stdErrText);

    AuthSessionPtr m_session;
    QString m_stdErr;
    bool m_running = false;
};
