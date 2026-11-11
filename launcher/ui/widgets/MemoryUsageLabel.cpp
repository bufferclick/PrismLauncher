// SPDX-License-Identifier: GPL-3.0-only
/*
 *  JL - Minecraft Launcher
 *  Copyright (C) 2026 Buffer (JLac)
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 */

#include "MemoryUsageLabel.h"

#include <QRegularExpression>

MemoryUsageLabel::MemoryUsageLabel(QWidget* parent) : QLabel(parent)
{
    setObjectName(QStringLiteral("memoryUsageLabel"));
    setToolTip(tr("Heap used by the running game, as reported by the game itself.\n"
                  "This is Java heap usage, not total process memory."));
    setTextInteractionFlags(Qt::TextSelectableByMouse);
    reset();
}

void MemoryUsageLabel::setMaxMiB(int mib)
{
    m_maxMiB = qMax(0, mib);
    updateText();
}

void MemoryUsageLabel::reset()
{
    m_usedMiB = -1;
    m_totalMiB = -1;
    m_lastSample.invalidate();
    updateText();
}

bool MemoryUsageLabel::handleLogLine(const QString& line)
{
    // Vanilla's F3 line: "Memory: 123/456 MB". Some versions print "Memory: 123 MB / 456 MB".
    static const QRegularExpression re(QStringLiteral("Memory:\\s*([0-9]+)\\s*(?:/\\s*|MB\\s*/\\s*)([0-9]+)\\s*MB"));
    const auto match = re.match(line);
    if (!match.hasMatch())
        return false;

    bool usedOk = false, totalOk = false;
    const int used = match.captured(1).toInt(&usedOk);
    const int total = match.captured(2).toInt(&totalOk);
    if (!usedOk || !totalOk)
        return false;

    m_usedMiB = used;
    m_totalMiB = total;
    m_lastSample.start();
    updateText();
    return true;
}

void MemoryUsageLabel::updateText()
{
    if (m_maxMiB <= 0 && m_usedMiB < 0) {
        setText(tr("Memory: –"));
        return;
    }

    // Prefer the JVM's own ceiling; fall back to whatever the game reported as total.
    const int maxMiB = m_maxMiB > 0 ? m_maxMiB : m_totalMiB;
    if (m_usedMiB < 0) {
        setText(tr("Memory: – / %1 MB").arg(maxMiB));
        return;
    }

    const int percent = maxMiB > 0 ? qRound(100.0 * m_usedMiB / maxMiB) : 0;
    setText(tr("Memory: %1% · %2 / %3 MB").arg(percent).arg(m_usedMiB).arg(maxMiB));

    // Colour the readout once the heap gets tight, the way the F3 bar does.
    const QString colour = percent >= 90 ? QStringLiteral("#e5534b") : percent >= 75 ? QStringLiteral("#d29922") : QString();
    if (colour.isEmpty())
        setStyleSheet(QString());
    else
        setStyleSheet(QStringLiteral("color: %1;").arg(colour));
}
