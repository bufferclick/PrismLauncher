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

#include <QPointer>

#include "ExternalResourcesPage.h"

/**
 * Content mods for a Horizon instance.
 *
 * Horizon reads `.hmod` content mods from `game/horizon-mods/` and turns each
 * one on or off with a `mod.<id>:true|false` line in `game/horizon-mods.txt`.
 * Those are the engine's own rules (`docs/api/content.md`), and they are also
 * what the game's Options -> Mods screen writes, so the two views never
 * disagree.
 *
 * Every operation goes through the toolkit (`mod check`, `mod install`,
 * `mod enable`, `mod disable`) rather than being re-implemented here: a `.hmod`
 * that the toolkit accepts is one the engine will load, and a file the engine
 * would refuse is rejected before it reaches the game folder.
 */
class HorizonModFolderPage : public ExternalResourcesPage {
    Q_OBJECT

   public:
    explicit HorizonModFolderPage(MinecraftInstance* inst, QWidget* parent = nullptr);
    ~HorizonModFolderPage() override = default;

    QString displayName() const override { return tr("Mods"); }
    QIcon icon() const override { return QIcon::fromTheme("loadermods"); }
    QString id() const override { return "horizonmods"; }
    QString helpPage() const override { return "Mods"; }

    bool shouldDisplay() const override { return true; }

   public slots:
    void updateFrame(const QModelIndex& current, const QModelIndex& previous) override;

   protected:
    void addItem() override;

   private:
    void installMods();
    void toggleSelected(bool enabled);

    ResourceFolderModel* m_model = nullptr;
    QPointer<QPushButton> m_enableButton;
    QPointer<QPushButton> m_disableButton;
};
