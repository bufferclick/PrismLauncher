// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (C) 2026 JL contributors
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "HorizonModFolderPage.h"

#include "ui_ExternalResourcesPage.h"

#include <QFileDialog>
#include <QMessageBox>
#include <QPushButton>

#include "Application.h"
#include "FileSystem.h"
#include "minecraft/horizon/HorizonPort.h"
#include "minecraft/horizon/HorizonInstance.h"
#include "minecraft/mod/ResourceFolderModel.h"

namespace {
QString selectedModId(const QModelIndex& index)
{
    if (!index.isValid())
        return {};
    return index.data(Qt::UserRole + 1).toString();
}
}  // namespace

HorizonModFolderPage::HorizonModFolderPage(MinecraftInstance* inst, QWidget* parent)
    : ExternalResourcesPage(inst,
                            // The engine reads .hmod files from game/horizon-mods;
                            // the model watches exactly that folder, so a file added
                            // by the game also appears here.
                            new ResourceFolderModel(QDir(static_cast<HorizonInstance*>(inst)->modsRoot()), inst,
                                                    /*isIndexed=*/false, /*createDir=*/true, parent),
                            parent)
{
    auto* horizon = static_cast<HorizonInstance*>(inst);

    // Not a ModFolderPage: that one offers CurseForge/Modrinth browsing, which
    // cannot serve .hmod content and would only lead to dead ends.
    m_ui->actionAddItem->setText(tr("Add Mod"));
    m_ui->actionAddItem->setToolTip(tr("Install a Horizon content mod (.hmod)"));
    m_ui->actionRemoveItem->setText(tr("Remove Mod"));
    // Nothing here can be checked for updates: a .hmod carries its own version
    // and the toolkit has no remote registry to compare against.
    m_ui->actionUpdateItem->setVisible(false);
    m_ui->actionChangeVersion->setVisible(false);

    m_enableButton = new QPushButton(tr("Enable"), this);
    m_disableButton = new QPushButton(tr("Disable"), this);
    connect(m_enableButton, &QPushButton::clicked, this, [this] { toggleSelected(true); });
    connect(m_disableButton, &QPushButton::clicked, this, [this] { toggleSelected(false); });
}

void HorizonModFolderPage::addItem()
{
    installMods();
}

void HorizonModFolderPage::installMods()
{
    const auto files = QFileDialog::getOpenFileNames(this, tr("Install Horizon content mods"), QString(),
                                                     tr("Horizon content mods (*.hmod)"));
    if (files.isEmpty())
        return;

    auto* horizon = static_cast<HorizonInstance*>(m_instance);
    QStringList failures;
    for (const auto& file : files) {
        QString error;
        QJsonObject report;
        // The toolkit checks the file the way the engine would before it is
        // copied anywhere, so a mod that would not load is refused here with
        // the reason instead of silently failing in the game.
        if (!HorizonPort::run({ "mod", "install", file, "--instance", horizon->name() }, &report, &error))
            failures << QStringLiteral("%1: %2").arg(QFileInfo(file).fileName(), error);
    }
    if (m_model)
        m_model->update();

    if (!failures.isEmpty()) {
        QMessageBox::warning(this, tr("Some mods were not installed"),
                             tr("These files would not load:\n\n%1").arg(failures.join('\n')));
    }
}

void HorizonModFolderPage::toggleSelected(bool enabled)
{
    const auto indexes = m_ui->treeView->selectionModel()->selectedRows();
    if (indexes.isEmpty())
        return;

    auto* horizon = static_cast<HorizonInstance*>(m_instance);
    QStringList failures;
    for (const auto& index : indexes) {
        const QString modId = selectedModId(index);
        if (modId.isEmpty())
            continue;
        QString error;
        if (!HorizonPort::run({ "mod", enabled ? "enable" : "disable", modId, "--instance", horizon->name() }, nullptr, &error))
            failures << QStringLiteral("%1: %2").arg(modId, error);
    }
    if (!failures.isEmpty())
        QMessageBox::warning(this, tr("Some mods could not be changed"), failures.join('\n'));

    // "Applies at next start": the engine reads horizon-mods.txt on start.
    if (m_model)
        m_model->update();
}

void HorizonModFolderPage::updateFrame(const QModelIndex& current, const QModelIndex& previous)
{
    ExternalResourcesPage::updateFrame(current, previous);
    if (!m_enableButton || !m_disableButton)
        return;
    const bool hasSelection = current.isValid();
    m_enableButton->setEnabled(hasSelection);
    m_disableButton->setEnabled(hasSelection);
}
