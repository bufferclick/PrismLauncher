// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "DebugModeDialog.h"
#include "DebugReport.h"

#include <QClipboard>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QGuiApplication>
#include <QHBoxLayout>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QStandardPaths>
#include <QTextCursor>
#include <QTextStream>
#include <QTimer>
#include <QVBoxLayout>
#include <QElapsedTimer>

#include "Application.h"
#include "BuildConfig.h"
#include "InstanceList.h"

DebugModeDialog::DebugModeDialog(QWidget* parent) : QDialog(parent)
{
    setWindowTitle(tr("JL Debug Mode"));
    resize(900, 640);

    auto* layout = new QVBoxLayout(this);

    m_text = new QPlainTextEdit(this);
    m_text->setReadOnly(true);
    m_text->setLineWrapMode(QPlainTextEdit::NoWrap);
    m_text->setPlaceholderText(tr("Collecting…"));
    layout->addWidget(m_text, 1);

    auto* buttons = new QHBoxLayout();
    buttons->addWidget(m_benchmark = new QPushButton(tr("Run benchmark"), this));
    buttons->addStretch(1);
    buttons->addWidget(m_refresh = new QPushButton(tr("Refresh"), this));
    buttons->addWidget(m_copy = new QPushButton(tr("Copy report"), this));
    buttons->addWidget(m_save = new QPushButton(tr("Save report…"), this));
    layout->addLayout(buttons);

    connect(m_refresh, &QPushButton::clicked, this, &DebugModeDialog::refresh);
    connect(m_copy, &QPushButton::clicked, this, &DebugModeDialog::copyReport);
    connect(m_save, &QPushButton::clicked, this, &DebugModeDialog::saveReport);
    connect(m_benchmark, &QPushButton::clicked, this, &DebugModeDialog::runBenchmark);

    // Collect once the dialog is on screen so the user sees progress rather than a freeze.
    QTimer::singleShot(0, this, &DebugModeDialog::refresh);
}

void DebugModeDialog::refresh()
{
    m_report = DebugReport::collect();
    m_text->setPlainText(m_report);
}

void DebugModeDialog::copyReport()
{
    QGuiApplication::clipboard()->setText(m_report);
    QMessageBox::information(this, tr("Copied"), tr("The report is on your clipboard."));
}

void DebugModeDialog::saveReport()
{
    const auto path = QFileDialog::getSaveFileName(this, tr("Save debug report"),
                                                   QDir(QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation))
                                                       .absoluteFilePath(DebugReport::suggestedFileName()),
                                                   tr("Text files (*.txt);;All files (*)"));
    if (path.isEmpty())
        return;

    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        QMessageBox::warning(this, tr("Could not save"), tr("Could not write to %1").arg(path));
        return;
    }
    QTextStream stream(&file);
    stream << m_report;
    QMessageBox::information(this, tr("Saved"), tr("Saved to %1").arg(path));
}

void DebugModeDialog::runBenchmark()
{
    // Measure the things people actually complain about. Each is a local operation with no
    // network access, timed with a monotonic clock so the numbers are comparable.
    QStringList lines;
    lines << QString();
    lines << QStringLiteral("=== Benchmark ===");

    QElapsedTimer timer;

    // 1. Instance scan: how long the launcher takes to look at every instance on disk.
    timer.start();
    const auto list = APPLICATION->instances();
    const int count = list->count();
    const qint64 scanMs = timer.elapsed();
    lines << QStringLiteral("Instance scan (%1 instances): %2 ms").arg(count).arg(scanMs);

    // 2. Process spawn: the floor for "launch a JVM", which dominates mod-test turnaround.
    const auto java = QStandardPaths::findExecutable(QStringLiteral("java"));
    if (!java.isEmpty()) {
        timer.start();
        QProcess proc;
        proc.start(java, { "-version" });
        proc.waitForFinished(10000);
        lines << QStringLiteral("Cold `java -version`: %1 ms").arg(timer.elapsed());
    } else {
        lines << QStringLiteral("Cold `java -version`: (no java on PATH)");
    }

    // 3. Metadata cache: the JSON Prism reads before it can show versions.
    QDir metaDir(QDir(APPLICATION->dataRoot()).absoluteFilePath(QStringLiteral("meta")));
    timer.start();
    const auto metaFiles = metaDir.entryInfoList(QDir::Files);
    qint64 metaBytes = 0;
    for (const auto& entry : metaFiles) {
        metaBytes += entry.size();
    }
    lines << QStringLiteral("Metadata folder scan: %1 ms (%2 files, %3 bytes)")
                 .arg(timer.elapsed())
                 .arg(metaFiles.size())
                 .arg(metaBytes);

    lines << QString();
    lines << QStringLiteral("Copy this block back to whoever is debugging with you.");

    m_report += lines.join('\n');
    m_text->setPlainText(m_report);
    m_text->moveCursor(QTextCursor::End);
}
