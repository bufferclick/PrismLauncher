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

#include <QPointer>

#include "ModFolderPage.h"

class HorizonInstance;
class ModFolderModel;
class QProcess;

/**
 * The Mods page for a Horizon instance.
 *
 * Horizon native mods (.hnmod) are Rust source, not jars: Horizon's launcher compiles them into
 * the game before it can run. So this page keeps the normal add/remove behaviour and adds the
 * one action that matters for Horizon: "Build Mods", which runs
 * `horizon-launcher native-build <mods> --trust-native-code` and streams the output.
 */
class HorizonModFolderPage : public ModFolderPage {
    Q_OBJECT

   public:
    explicit HorizonModFolderPage(HorizonInstance* inst, ModFolderModel* model, QWidget* parent = nullptr);

    QString displayName() const override { return tr("Mods"); }
    QString helpPage() const override { return "Loader-mods"; }

   private slots:
    void buildMods();

   private:
    void appendBuildOutput(const QString& text);
    void finishBuild(int exitCode, bool failedToStart);

    HorizonInstance* m_horizon = nullptr;
    QPointer<QProcess> m_build;
    QAction* m_buildAction = nullptr;
};

