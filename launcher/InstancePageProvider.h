#pragma once
#include <FileSystem.h>
#include <ui/pages/instance/DataPackPage.h>
#include "minecraft/MinecraftInstance.h"
#include "minecraft/horizon/HorizonInstance.h"
#include "ui/pages/BasePage.h"
#include "ui/pages/BasePageProvider.h"
#include "ui/pages/instance/InstanceSettingsPage.h"
#include "ui/pages/instance/LogPage.h"
#include "ui/pages/instance/ManagedPackPage.h"
#include "ui/pages/instance/ModFolderPage.h"
#include "ui/pages/instance/HorizonModFolderPage.h"
#include "ui/pages/instance/NotesPage.h"
#include "ui/pages/instance/OtherLogsPage.h"
#include "ui/pages/instance/ResourcePackPage.h"
#include "ui/pages/instance/ScreenshotsPage.h"
#include "ui/pages/instance/ServersPage.h"
#include "ui/pages/instance/ShaderPackPage.h"
#include "ui/pages/instance/TexturePackPage.h"
#include "ui/pages/instance/VersionPage.h"
#include "ui/pages/instance/WorldListPage.h"

class InstancePageProvider : protected QObject, public BasePageProvider {
    Q_OBJECT
   public:
    explicit InstancePageProvider(MinecraftInstance* parent) { inst = parent; }

    virtual ~InstancePageProvider() = default;
    virtual QList<BasePage*> getPages() override
    {
        QList<BasePage*> values;
        values.append(new LogPage(inst));
        values.append(new VersionPage(inst));
        values.append(ManagedPackPage::createPage(inst));
        // Horizon has its own content format (.hmod) and its own folder, read by
        // the engine from game/horizon-mods. Showing Java's mod folder here
        // would offer a page that can never load anything.
        if (inst->instanceType() == HorizonInstance::typeString()) {
            values.append(new HorizonModFolderPage(inst));
        } else {
            ModFolderPage* modsPage = new ModFolderPage(inst, inst->loaderModList());
            modsPage->setFilter("%1 (*.zip *.jar *.litemod *.nilmod)");
            values.append(modsPage);
        }
        values.append(new CoreModFolderPage(inst, inst->coreModList()));
        values.append(new NilModFolderPage(inst, inst->nilModList()));
        values.append(new ResourcePackPage(inst, inst->resourcePackList()));
        if (inst->instanceType() != HorizonInstance::typeString()) {
            values.append(new GlobalDataPackPage(inst));
        }
        values.append(new TexturePackPage(inst, inst->texturePackList()));
        values.append(new ShaderPackPage(inst, inst->shaderPackList()));
        values.append(new NotesPage(inst));
        values.append(new WorldListPage(inst, inst->worldList()));
        values.append(new ServersPage(inst));
        values.append(new ScreenshotsPage(FS::PathCombine(inst->gameRoot(), "screenshots")));
        values.append(new InstanceSettingsPage(inst));
        values.append(new OtherLogsPage("logs", tr("Other Logs"), "Other-Logs", inst));
        return values;
    }

    virtual QString dialogTitle() override { return tr("Edit Instance (%1)").arg(inst->name()); }

   protected:
    MinecraftInstance* inst;
};
