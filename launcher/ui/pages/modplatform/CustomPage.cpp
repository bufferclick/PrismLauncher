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
    }

    updateLoaderUi();
    suggestCurrent();
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
    // Horizon is its own client built for a single Minecraft version. There is no version to
    // pick and no loader build to pick, so both choosers are hidden and the page just says
    // what the instance will be.
    if (m_ui->horizonFilter->isChecked()) {
        m_selectedVersion.reset();
        m_selectedLoader.clear();
        m_selectedLoaderVersion.reset();
        updateLoaderUi();
        suggestCurrent();
        return;
    }

    updateLoaderUi();

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

void CustomPage::updateLoaderUi()
{
    const bool horizon = m_ui->horizonFilter->isChecked();

    // With Horizon there is nothing to choose, so the version picker, the separator and the
    // loader picker are all hidden and the summary takes their place.
    m_ui->minecraftGroup->setVisible(!horizon);
    m_ui->loaderLine->setVisible(!horizon);
    m_ui->loaderGroup->setVisible(!horizon);
    m_ui->horizonSummary->setVisible(horizon);
    m_ui->browseFabricButton->setVisible(!horizon);

    m_ui->horizonVersionLabel->setText(tr("Minecraft %1").arg(HorizonCreationTask::gameVersion()));

    m_ui->pageTitle->setText(horizon ? tr("New Horizon instance") : tr("New Fabric instance"));
    m_ui->pageSubtitle->setText(horizon ? tr("Horizon is a complete client of its own — nothing to configure here.")
                                        : tr("Pick a Minecraft version, then a Fabric loader build."));
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
    // The title and subtitle are also set in code (Horizon vs Fabric), so re-apply whichever
    // one the current loader selection calls for.
    updateLoaderUi();
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

    // Horizon needs no version: the task knows the one version Horizon runs.
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
    // The version list keeps loading in the background after switching to Horizon; ignoring it
    // avoids re-running the Fabric loader lookup the user no longer asked for.
    if (m_ui->horizonFilter->isChecked()) {
        return;
    }
    suggestCurrent();
    loaderFilterChanged();
}

void CustomPage::setSelectedLoaderVersion(BaseVersion::Ptr version)
{
    m_selectedLoaderVersion = std::move(version);
    suggestCurrent();
}
