// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Prism Launcher - Minecraft Launcher
 *  Copyright (c) 2022 Jamie Mansfield <jmansfield@cadixdev.org>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * This file incorporates work covered by the following copyright and
 * permission notice:
 *
 *      Copyright 2013-2021 MultiMC Contributors
 *
 *      Licensed under the Apache License, Version 2.0 (the "License");
 *      you may not use this file except in compliance with the License.
 *      You may obtain a copy of the License at
 *
 *          http://www.apache.org/licenses/LICENSE-2.0
 *
 *      Unless required by applicable law or agreed to in writing, software
 *      distributed under the License is distributed on an "AS IS" BASIS,
 *      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *      See the License for the specific language governing permissions and
 *      limitations under the License.
 */

#include "CustomPage.h"
#include "ui_CustomPage.h"

#include <QTabBar>
#include <utility>

#include "Application.h"
#include "Filter.h"
#include "Version.h"
#include "meta/Index.h"
#include "meta/VersionList.h"
#include "minecraft/HorizonCreationTask.h"
#include "minecraft/VanillaInstanceCreationTask.h"
#include "ui/dialogs/FabricVersionsDialog.h"
#include "ui/dialogs/NewInstanceDialog.h"

CustomPage::CustomPage(NewInstanceDialog* dialog, QWidget* parent) : QWidget(parent), m_dialog(dialog), m_ui(new Ui::CustomPage)
{
    m_ui->setupUi(this);
    connect(m_ui->versionList, &VersionSelectWidget::selectedVersionChanged, this, &CustomPage::setSelectedVersion);
    filterChanged();
    connect(m_ui->alphaFilter, &QCheckBox::checkStateChanged, this, &CustomPage::filterChanged);
    connect(m_ui->betaFilter, &QCheckBox::checkStateChanged, this, &CustomPage::filterChanged);
    connect(m_ui->snapshotFilter, &QCheckBox::checkStateChanged, this, &CustomPage::filterChanged);
    connect(m_ui->releaseFilter, &QCheckBox::checkStateChanged, this, &CustomPage::filterChanged);
    connect(m_ui->experimentsFilter, &QCheckBox::checkStateChanged, this, &CustomPage::filterChanged);
    connect(m_ui->refreshBtn, &QPushButton::clicked, this, &CustomPage::refresh);

    connect(m_ui->loaderVersionList, &VersionSelectWidget::selectedVersionChanged, this, &CustomPage::setSelectedLoaderVersion);
    connect(m_ui->fabricFilter, &QRadioButton::toggled, this, &CustomPage::loaderFilterChanged);
    connect(m_ui->horizonFilter, &QRadioButton::toggled, this, &CustomPage::loaderFilterChanged);
    connect(m_ui->loaderRefreshBtn, &QPushButton::clicked, this, &CustomPage::loaderRefresh);
    connect(m_ui->browseFabricButton, &QPushButton::clicked, this, [this] {
        FabricVersionsDialog dialog(this);
        dialog.exec();
    });
}

void CustomPage::openedImpl()
{
    if (!m_initialized) {
        auto vlist = APPLICATION->metadataIndex()->get("net.minecraft");
        m_ui->versionList->initialize(vlist.get());
        m_initialized = true;
        // Fabric is preselected and always on.
        m_ui->fabricFilter->setChecked(true);
    } else {
        suggestCurrent();
    }
}

void CustomPage::refresh()
{
    m_ui->versionList->loadList(true);
}

void CustomPage::loaderRefresh()
{
    m_ui->loaderVersionList->loadList(true);
}

void CustomPage::filterChanged()
{
    QStringList out;
    if (m_ui->alphaFilter->isChecked()) {
        out << "(alpha)";
    }
    if (m_ui->betaFilter->isChecked()) {
        out << "(beta)";
    }
    if (m_ui->snapshotFilter->isChecked()) {
        out << "(snapshot)";
    }
    if (m_ui->releaseFilter->isChecked()) {
        out << "(release)";
    }
    if (m_ui->experimentsFilter->isChecked()) {
        out << "(experiment)";
    }
    auto regexp = out.join('|');
    m_ui->versionList->setFilter(BaseVersionList::TypeRole, Filters::regexp(QRegularExpression(regexp)));
}

void CustomPage::loaderFilterChanged()
{
    // Horizon is a separate native client, not a version the metadata index knows about, so
    // it never has a loader list: the page just explains what the instance will do.
    if (m_ui->horizonFilter->isChecked()) {
        m_selectedLoader.clear();
        m_selectedLoaderVersion.reset();
        // No loader versions to list: Horizon is not built from Minecraft libraries. (This is
        // the same "match nothing" sentinel the vanilla branch below uses.)
        m_ui->loaderVersionList->setExactFilter(BaseVersionList::ParentVersionRole, "AAA");
        m_ui->loaderVersionList->setEmptyString(
            tr("Horizon runs its own Rust client. The instance keeps its mods (.hnmod), "
               "resource packs and saves in this folder, and Help → Horizon installs the client."));
        m_ui->loaderVersionList->setEmptyMode(VersionListView::String);
        suggestCurrent();
        return;
    }

    const QString minecraftVersion = m_selectedVersion ? m_selectedVersion->descriptor() : QString();
    if (minecraftVersion.isEmpty()) {
        m_ui->loaderVersionList->setExactFilter(BaseVersionList::ParentVersionRole, "AAA");  // empty list
        m_ui->loaderVersionList->setEmptyString(tr("Pick a Minecraft version first."));
        m_ui->loaderVersionList->setEmptyMode(VersionListView::String);
        return;
    }

    m_selectedLoader = "net.fabricmc.fabric-loader";

    // Fabric supports Minecraft 1.14 and newer. Hide the list entirely for older
    // versions instead of offering something that cannot work.
    if (Version(minecraftVersion) < Version("1.14")) {
        m_selectedLoaderVersion.reset();
        m_ui->loaderVersionList->setExactFilter(BaseVersionList::ParentVersionRole, "AAA");  // empty list
        m_ui->loaderVersionList->setEmptyString(tr("Fabric does not support Minecraft %1. Pick 1.14 or newer.").arg(minecraftVersion));
        m_ui->loaderVersionList->setEmptyMode(VersionListView::String);
        suggestCurrent();
        return;
    }

    // FIXME: dirty hack because the launcher is unaware of Fabric's dependencies
    m_ui->loaderVersionList->setExactFilter(BaseVersionList::ParentVersionRole, "");

    auto vlist = APPLICATION->metadataIndex()->get(m_selectedLoader);
    m_ui->loaderVersionList->initialize(vlist.get());
    m_ui->loaderVersionList->selectRecommended();
    m_ui->loaderVersionList->setEmptyString(tr("No Fabric builds are available for Minecraft %1 yet.").arg(minecraftVersion));
}

CustomPage::~CustomPage()
{
    delete m_ui;
}

bool CustomPage::shouldDisplay() const
{
    return true;
}

void CustomPage::retranslate()
{
    m_ui->retranslateUi(this);
}

BaseVersion::Ptr CustomPage::selectedVersion() const
{
    return m_selectedVersion;
}

BaseVersion::Ptr CustomPage::selectedLoaderVersion() const
{
    return m_selectedLoaderVersion;
}

QString CustomPage::selectedLoader() const
{
    return m_selectedLoader;
}

QString CustomPage::selectedLoaderName() const
{
    if (m_ui->horizonFilter->isChecked())
        return QStringLiteral("Horizon");
    return QStringLiteral("Fabric");
}

void CustomPage::suggestCurrent()
{
    if (!isOpened) {
        return;
    }

    if (m_ui->horizonFilter->isChecked()) {
        m_dialog->setSuggestedPack(QStringLiteral("Horizon"), new HorizonCreationTask());
        m_dialog->setSuggestedIcon("default");
        return;
    }

    if (!m_selectedVersion) {
        m_dialog->setSuggestedPack();
        return;
    }

    // Fabric needs 1.14+. Older versions can only be installed vanilla, so be
    // explicit about it instead of silently dropping the loader.
    if (m_selectedLoaderVersion == nullptr) {
        if (Version(m_selectedVersion->descriptor()) < Version("1.14")) {
            m_dialog->setSuggestedPack(m_selectedVersion->descriptor(), new VanillaCreationTask(m_selectedVersion));
        } else {
            m_dialog->setSuggestedPack();
        }
    } else {
        QString suggestedName = QString("%1 %2").arg(m_selectedVersion->descriptor(), selectedLoaderName());
        m_dialog->setSuggestedPack(suggestedName, new VanillaCreationTask(m_selectedVersion, m_selectedLoader, m_selectedLoaderVersion));
    }
    m_dialog->setSuggestedIcon("default");
}

void CustomPage::setSelectedVersion(BaseVersion::Ptr version)
{
    m_selectedVersion = std::move(version);
    suggestCurrent();
    loaderFilterChanged();
}

void CustomPage::setSelectedLoaderVersion(BaseVersion::Ptr version)
{
    m_selectedLoaderVersion = std::move(version);
    suggestCurrent();
}
